# -*- coding: utf-8 -*-
import itertools
import calendar
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DF
from odoo.tools import float_compare, float_is_zero
from lxml import etree


class Asset(models.Model):
    _name = 'asset_management.asset'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Asset Number", index=True, readonly=True, track_visibility='always')
    description = fields.Text("Description", required=True, track_visibility='onchange')
    ownership_type = fields.Selection(selection=[('owned', 'Owned')], default='owned', track_visibility='onchange')
    is_new = fields.Selection(selection=[('new', 'New')
        , ('used', 'Used')], default='new', track_visibility='onchange')
    is_in_physical_inventory = fields.Boolean(default=True, track_visibility='onchange')
    in_use_flag = fields.Boolean(default=True, track_visibility='onchange')
    parent_asset = fields.Many2one('asset_management.asset', on_delete='cascade', track_visibility='onchange')
    item_id = fields.Many2one('product.product', on_delete='set_null', required=True, track_visibility='onchange')
    category_id = fields.Many2one('asset_management.category', required=True, domain=[('active', '=', True)],
                                  track_visibility='onchange')
    book_assets_id = fields.One2many(comodel_name="asset_management.book_assets", inverse_name="asset_id",
                                     string="Book", on_delete='cascade')
    depreciation_line_ids = fields.One2many(comodel_name="asset_management.depreciation", inverse_name="asset_id",
                                            string="depreciation", on_delete='cascade')
    asset_serial_number = fields.Char(string='Serial Number', track_visibility='onchange')
    asset_tag_number = fields.Many2many('asset_management.tag', relation="asset_tag",column1="asset_id",column2="tag_id",track_visibility='onchange')
    serial_flag = fields.Boolean()
    asset_with_category = fields.Boolean(related='category_id.asset_with_category')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, readonly=True,
                                  default=lambda self: self.env.user.company_id.currency_id.id)
    entry_asset_count = fields.Integer(compute='_entry_asset_count', string='# Asset Entries')
    transaction_id = fields.One2many('asset_management.transaction', inverse_name="asset_id", on_delete="cascade")
    category_invisible = fields.Boolean()
    asset_type = fields.Selection([
        ('expense', 'Expense'),
        ('capitalize', 'Capitalize')
    ], required=True, track_visibility='onchange')
    asset_with_one2many = fields.Boolean(default=True)

    #     @api.onchange('item_id')
    #     def _test_tracking_in_item(self):
    #         if self.item_id:
    #             if self.item_id.tracking == 'lot' or self.item_id.tracking == 'serial':
    #                 self.serial_flag= True
    #             else:
    #                 self.serial_flag = False

#uniqe asset on based of serial and tag number
    @api.constrains('asset_serial_number', 'asset_tag_number')
    def _unique_serial_tag_number_on_asset(self):
        for rec in self:
            x = self.env['asset_management.asset'].search([('asset_serial_number', '=',rec.asset_serial_number),('id','!=',self.id)])
            if x:
                for xx in x:
                    p_id = [p.id for p in xx.asset_tag_number]
                    a_id = [a.id for a in self.asset_tag_number]
                    if set(a_id) == frozenset(p_id):
                        raise ValidationError(_('Asset Serial and Tag Number must be UNIQUE'))

    @api.onchange('category_id')
    def _get_default_values_for_asset(self):
        if self.category_id:
            self.ownership_type = self.category_id.ownership_type
            self.is_in_physical_inventory = self.category_id.is_in_physical_inventory

    # open account.move list view
    @api.multi
    def open_asset_entries(self):
        move_ids = []
        for asset in self:
            for depreciation_line in asset.depreciation_line_ids:
                if depreciation_line.move_id:
                    move_ids.append(depreciation_line.move_id.id)
        return {
            'name': _('Journal Entries'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'account.move',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', move_ids)],
        }

    # compute number of moved depreciation line
    @api.multi
    @api.depends('depreciation_line_ids.move_id')
    def _entry_asset_count(self):
        for asset in self:
            res = asset.env['asset_management.depreciation'].search_count(
                [('asset_id', '=', asset.id), ('move_id', '!=', False)])
            asset.entry_asset_count = res or 0

    @api.model
    def create(self, values):
        values['name'] = self.env['ir.sequence'].next_by_code('asset_management.asset.Asset')
        if 'book_assets_id' not in values:
            raise ValidationError(_('Asset must be added to a book'))
        return super(Asset, self).create(values)

    # generat mas entries from Generate Asset Entries wizard
    @api.multi
    def generate_mas_entries(self, period_id, post_entries, book_id, run_number_process):
        new_moved_lines = []
        old_moved_lines = []
        capitalized_asset = self.env['asset_management.book_assets'].search(
            [('state', '=', 'open'), ('book_id', '=', book_id), ('depreciated_flag', '=', True)])
        # if date_from < capitalized_asset[0].book_id.calendar_line_id.start_date or date_to > capitalized_asset[0].book_id.calendar_line_id.end_date:
        #     raise ValidationError(_("Period of generate entries is not in current fiscal period "))
        for entries in capitalized_asset:
            dep_line = self.env['asset_management.depreciation'].search(
                [('asset_id', '=', entries.asset_id.id), ('book_id', '=', book_id)
                    , ('depreciation_date', '<=', period_id.end_date), ('move_posted_check', '=', False)])
            trx_lines = self.env['asset_management.transaction'].search(
                [('asset_id', '=', entries.asset_id.id), ('book_id', '=', book_id),
                 ('trx_date', '<=', period_id.end_date), ('move_posted_check', '=', False)])
            sequence = 0
            for deprecation in dep_line:
                if not deprecation.move_check:
                    deprecation.create_move()
                    # deprecation.dep_run_process_id = run_number_process
                    deprecation.write({'dep_run_process_id': run_number_process,
                                       'period_id': period_id.id})
                    sequence += 1
                    self.env['asset_management.deprunprocess_line'].create({'sequence': sequence,
                                                                            'dep_run_process_id': run_number_process,
                                                                            'depreciation_id': deprecation.id})
                    new_moved_lines += deprecation
                else:
                    old_moved_lines += deprecation

            for trx in trx_lines:
                if not trx.move_check and not trx.asset_id.asset_type == 'expense':
                    if trx.trx_type == 'full_retirement' or trx.trx_type == 'partial_retirement':
                        trx.generate_retirement_journal()
                        new_moved_lines += trx
                    else:
                        trx.create_trx_move()
                        new_moved_lines += trx
                else:
                    old_moved_lines += trx
        if not post_entries:
            return new_moved_lines
        else:
            new_moved_lines += old_moved_lines
            return new_moved_lines

    @api.multi
    def post_lines_and_close_asset(self, book_id):
        # we re-evaluate the assets to determine whether we can close them
        for line in self:
            # line.log_message_when_posted()
            # asset = line.asset_id
            # book=line.book_id
            book_asset = line.env['asset_management.book_assets'].search(
                [('asset_id', '=', line.id), ('book_id', '=', book_id)])
            residual_value = book_asset[0].residual_value
            current_currency = self.env['res.company'].search([('id', '=', 1)])[0].currency_id
            if current_currency.is_zero(residual_value):
                # asset.message_post(body=_("Document closed."))
                book_asset.write({'state': 'close'})

    @api.multi
    def unlink(self):
        raise ValidationError(_('Asset can not be deleted '))
        super(Asset, self).unlink()



class Category(models.Model):
    _name = 'asset_management.category'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string='Category Name', index=True, required=True, track_visibility='always')
    description = fields.Text(required=True, track_visibility='onchange')
    ownership_type = fields.Selection(selection=[('owned', 'Owned')], default='owned', track_visibility='onchange')
    is_in_physical_inventory = fields.Boolean(default=True, track_visibility='onchange')
    category_books_id = fields.One2many('asset_management.category_books', inverse_name='category_id',
                                        on_delete='cascade', )
    depreciation_method = fields.Selection([('linear', 'Linear'), ('degressive', 'Degressive')],
                                           default='linear', track_visibility='onchange')
    asset_with_category = fields.Boolean()
    active = fields.Boolean(default=True, track_visibility='onchange')
    category_one2many_view = fields.Boolean(default=True, readonly=True)
    _sql_constraints = [
        ('category_name', 'UNIQUE(name)', 'Category name already exist..!')
    ]

    @api.model
    def create(self, values):
        if 'category_books_id' not in values:
            raise ValidationError(_('Category must be added to a book'))
        return super(Category, self).create(values)

    @api.multi
    def unlink(self):
        for record in self:
            category_in_asset = record.env['asset_management.book_asset'].search([('category_id', '=', record.id)])[0]
            if category_in_asset:
                raise ValidationError(_('Category can not be deleted '))
        super(Category, self).unlink()


class Book(models.Model):
    _name = 'asset_management.book'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(index=True, required=True, track_visibility='always')
    description = fields.Text(required=True, track_visibility='onchange')
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env['res.company']._company_default_get(
                                     'asset_management.book'), track_visibility='onchange')
    cost_of_removal_gain_account = fields.Many2one('account.account', on_delete='set_null', track_visibility='onchange')
    cost_of_removal_loss_account = fields.Many2one('account.account', on_delete='set_null', track_visibility='onchange')
    book_with_cate = fields.Boolean()
    active = fields.Boolean(default=True, track_visibility='onchange')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, compute="_compute_currency")
    calendar_id = fields.Many2one('asset_management.calendar', required=True, on_delete='cascade',
                                  track_visibility='onchange')
    calendar_line_id = fields.Many2one('asset_management.calendar_line', required=True, on_delete="set_null",
                                       string='Period', track_visibility='onchange')
    fiscal_year = fields.Char(compute="_compute_fiscal_year", track_visibility='onchange')
    _sql_constraints = [
        ('book_name', 'UNIQUE(name)', 'Book name already exist..!')
    ]
    gain_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                               track_visibility='onchange')
    gain_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                             track_visibility='onchange')
    loss_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                               track_visibility='onchange')
    loss_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                             track_visibility='onchange')
    allow_future_transaction = fields.Boolean(track_visibility='onchange')

    @api.multi
    def open_next_period(self, period):
        for record in self.calendar_line_id.calendar_id:
            periods = record.calendar_lines_id.sorted(key=lambda l: l.end_date)
            for a, b in zip(periods, periods[1:]):
                if a.id == period:
                    self.write({'calendar_line_id': b.id})

    @api.depends('calendar_line_id')
    def _compute_fiscal_year(self):
        for record in self:
            if record.calendar_line_id:
                record.fiscal_year = str(record.calendar_line_id.start_date.strftime("%Y"))
                # datetime.strptime(record.start_date,DF).year

    @api.onchange('calendar_id')
    def _calendar_line_id_domain(self):
        if self.calendar_id:
            return {'domain': {'calendar_line_id': [('calendar_id', '=', self.calendar_id.id)]
                               }}

    @api.depends('company_id')
    def _compute_currency(self):
        for record in self:
            record.currency_id = record.company_id.currency_id.id

    @api.onchange('company_id')
    def _cost_of_removal_gain_account_domain(self):
        for record in self:
            return {'domain': {'cost_of_removal_gain_account': [('company_id', '=', record.company_id.id)],
                               'cost_of_removal_loss_account': [('company_id', '=', record.company_id.id)],
                               'gain_analytic_account_id': [('company_id', '=', record.company_id.id)],
                               'loss_analytic_account_id': [('company_id', '=', record.company_id.id)]
                               }}

    @api.multi
    def unlink(self):
        for record in self:
            raise ValidationError(_(
                'Book deletion is prevented'))
        return super(Book, self).unlink()

    #
    # @api.onchange('company_id')
    # def _cost_of_removal_loss_account_domain(self):
    #     for record in self:
    #         # if record.cost_of_removal_loss_account:
    #             return {'domain': {'cost_of_removal_loss_account': [('company_id', '=',record.company_id.id)]
    #                            }}

    # @api.model
    # def move_to_next_period(self):
    #     for record in self:
    #         end_of_current_peroid = record.calendar_line_id.end_date


class BookAssets(models.Model):
    _name = 'asset_management.book_assets'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Book Asset Number", index=True)
    book_id = fields.Many2one('asset_management.book', on_delete='cascade', required=True, readonly=True,
                              states={'draft': [('readonly', False)]}, track_visibility='always')
    asset_id = fields.Many2one('asset_management.asset', on_delete='cascade', string='Asset', track_visibility='always',
                               readonly=True)
    depreciation_line_ids = fields.One2many(comodel_name='asset_management.depreciation', inverse_name='book_assets_id',
                                            on_delete='cascade', )
    depreciation_line_length = fields.Integer(compute="_depreciation_line_length")
    residual_value = fields.Float(string="Residual Value", compute='_amount_residual', required=True,
                                  track_visibility='onchange')
    salvage_value_amount = fields.Float(compute='_compute_salvage_value_amount', track_visibility='onchange')
    method = fields.Selection(
        [('linear', 'Linear'),
         ('degressive', 'Degressive')
         ], required=True, string='Depreciation Method', default='linear', readonly=True,
        states={'draft': [('readonly', False)]}, track_visibility='onchange')
    life_months = fields.Integer(required=True, track_visibility='onchange')
    end_date = fields.Date(track_visibility='onchange')
    original_cost = fields.Float(string='Original cost', required=True, track_visibility='onchange')
    current_cost = fields.Float(required=True, track_visibility='onchange', readonly=True)
    salvage_value_type = fields.Selection(
        [('amount', 'Amount'), ('percentage', 'Percentage')], default='amount', readonly=True,
        states={'draft': [('readonly', False)], 'open': [('readonly', False)]},
        track_visibility='onchange')
    salvage_value = fields.Float(string='Salvage Value', readonly=True,
                                 states={'draft': [('readonly', False)], 'open': [('readonly', False)]},
                                 track_visibility='onchange')
    date_in_service = fields.Date(string='Date In Service', required=True, readonly=True,
                                  states={'draft': [('readonly', False)]}, track_visibility='onchange')
    prorate_date = fields.Date(string='Prorate Date', compute="_compute_prorate_date", track_visibility='onchange')
    depreciated_flag = fields.Boolean(string='Depreciated', default=True, track_visibility='onchange')
    depreciation_computation = fields.Boolean(string='Depreciated', compute="_compute_depreciation_computation")
    method_progress_factor = fields.Float(string='Degressive Factor', default=0.3, track_visibility='onchange')
    method_number = fields.Integer(string='Number of Depreciation',
                                   help="The number of depreciations needed to depreciate your asset",
                                   track_visibility='onchange')
    # company_id = fields.Many2one('res.company', string='Company',default=lambda self: self.env['res.company']._company_default_get('asset_management.book_assets'))
    entry_count = fields.Integer(compute='_asset_entry_count', string='# Asset Entries')
    method_time = fields.Selection([('number', 'Number of Entries'), ('end', 'Ending Date')], string='Time Method',
                                   required=True, default='number', track_visibility='onchange',
                                   help="Choose the method to use to compute the dates and number of entries.\n"
                                        "  * Number of Entries: Fix the number of entries and the time between 2 depreciations.\n"
                                        "  * Ending Date: Choose the time between 2 depreciations and the date the depreciations won't go beyond.",
                                   readonly=True, states={'draft': [('readonly', False)]})
    state = fields.Selection([('draft', 'Draft'), ('open', 'Capitalize'), ('close', 'Close')], 'Status', required=True,
                             track_visibility='onchange',
                             copy=False, default='draft',
                             help="When an asset is created, the status is 'Draft'.\n"
                                  "If the asset is confirmed, the status goes in 'Running' and the depreciation lines can be posted in the accounting.\n"
                                  "You can manually close an asset when the depreciation is over. If the last line of depreciation is posted, the asset automatically goes in that status.")
    assignment_id = fields.One2many(comodel_name='asset_management.assignment', inverse_name='book_assets_id',
                                    on_delete='cascade')
    percentage = fields.Float(compute='_modify_percentage', store=True)
    category_id = fields.Many2one('asset_management.category', readonly=True,
                                  states={'draft': [('readonly', False)], 'open': [('readonly', False)]},
                                  track_visibility='onchange')
    source_line_ids = fields.One2many('asset_management.source_line', 'book_assets_id', on_delete='cascade', )
    # old_amount=fields.Float(compute="_amount_in_source_line")
    source_amount = fields.Float(compute="_amount_in_source_line", store=True)
    _sql_constraints = [('unique_book_id_on_asset', 'UNIQUE(asset_id,book_id)', 'asset already added to this book')]
    accumulated_value = fields.Float(readonly=True, track_visibility='onchange')
    net_book_value = fields.Float(compute='_compute_net_book_value', track_visibility='onchange')
    current_cost_from_retir = fields.Boolean()
    transaction_id = fields.One2many('asset_management.transaction', inverse_name="book_assets_id", on_delete="cascade")
    assign_change_flag = fields.Boolean()
    book_one2many_view = fields.Boolean(default=True, readonly=True)
    retirement_count = fields.Integer(compute='_asset_retirement_count')

    @api.multi
    @api.depends('asset_id', 'book_id')
    def _asset_retirement_count(self):
        for asset in self:
            res = self.env['asset_management.retirement'].search_count(
                [('asset_id', '=', self.asset_id.id), ('book_id', '=', self.book_id.id)])
            asset.retirement_count = res or 0

    @api.multi
    def open_retired_window(self):
        retirement_ids = self.env['asset_management.retirement'].browse(
            [('asset_id', '=', self.asset_id.id), ('book_id', '=', self.book_id.id)])
        return {
        'name': _('Retirement'),
        'type': 'ir.actions.act_window',
        'view_type': 'form',
        'view_mode': 'form',
        'res_model': 'asset_management.retirement',
        'target': 'current',
        'res_id':[('id', 'in', retirement_ids)],

    }

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(BookAssets, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('asset_with_one2many'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    @api.onchange('method_progress_factor')
    def _warning_for_dgressive_factor(self):
        if self.method_progress_factor < 0:
            warning = {
                'title': _('Warning!'),
                'message': _('Degressive Factor must be positive'),
            }
            return {'warning': warning}

    @api.depends('asset_id')
    def _compute_depreciation_computation(self):
        for asset in self:
            if asset.asset_id.asset_type == 'capitalize':
                asset.depreciation_computation = True

    @api.onchange('current_cost_from_retir')
    def _set_to_close(self):
        if self.current_cost_from_retir and self.current_cost_from_retir == True:
            if self.current_cost == 0:
                self.state = 'close'

    # @api.onchange('date_in_service')
    # def _onchange_date_in_service(self):
    #     if not self.date_in_service > self.book_id.calendar_line_id.start_date and not self.date_in_service < self.book_id.calendar_line_id.end_date :
    #         text =''
    #         if self.date_in_service < self.book_id.calendar_line_id.start_date :
    #             text = 'Asset is added in old period ,its depreciation would be in the current period'
    #
    #         elif self.date_in_service > self.book_id.calendar_line_id.end_date and  self.allow_future_transaction:
    #             text = 'Asset is added in future period ,its depreciation would be in the future period'
    #
    #         value = self.env['asset_management.confirmation_wizard'].sudo().create({'text': text,
    #                                                                         'date': self.date_in_service })
    #
    #         return {
    #             'type': 'ir.actions.act_window',
    #             'name': _('Warning'),
    #             'view_type': 'form',
    #             'view_mode': 'form',
    #             'res_model': 'asset_management.confirmation_wizard',
    #             'res_id': value.id,
    #             'target': 'new',
    #             'view_id': self.env.ref('asset_management.confirmation_wizard_form', False).id,
    #             'context': {'active_id':self.id}
    #
    #         }

    @api.constrains('method_progress_factor', 'date_in_service', 'current_cost')
    def _check_constraints(self):
        if self.date_in_service > self.book_id.calendar_line_id.end_date and not self.book_id.allow_future_transaction:
            raise ValidationError(
                _(
                    'In order to add assets in future period Allow Future Transaction in ' + self.book_id.name + ' must set to True'))

        if self.method_progress_factor < 0:
            raise ValidationError(_('Degressive Factor must be Positive'))

        if self.current_cost < 0:
            raise ValidationError(_('Current Cost can not be Negative'))

    @api.depends('accumulated_value', 'current_cost')
    def _compute_net_book_value(self):
        for record in self:
            record.net_book_value = record.current_cost - record.accumulated_value

    @api.onchange('current_cost')
    def _onchange_current_cost(self):
        if self.state == 'draft':
            self.original_cost = self.current_cost

    @api.onchange('assignment_id')
    def _onchange_assignment(self):
        if self.assignment_id and not self.source_line_ids:
            warning = {
                'title': _('Warning!'),
                'message': _('Add source line to asset..!'),
            }
            return {'warning': warning}
        if self.assignment_id:
            self.assign_change_flag = True

    @api.depends('source_line_ids')
    def _amount_in_source_line(self):
        for record in self:
            for source in record.source_line_ids:
                if source.source_type == 'invoice':
                    # record.current_cost += source.amount
                    record.source_amount += source.amount
                elif source.source_type == 'miscellaneous':
                    record.source_amount += source.amount_m_type
            record.current_cost = record.source_amount

    # @api.depends('source_amount')
    # def _compute_current_cost(self):
    #     for record in self:
    #        record.current_cost = record.source_amount

    # #to compute added value
    #     @api.depends('source_line_ids')
    #     def _amount_in_source_line(self):
    #         for record in self:
    #             for source in record.source_line_ids:
    #                 record.old_amount += source.amount
    #                 if record.old_amount < record.new_amount:
    #                     record.old_amount = record.new_amount

    # # to compute added value
    # @api.onchange('old_amount')
    # def _onchange_amount(self):
    #     for record in self:
    #         if record.old_amount:
    #             if (record.old_amount - record.new_amount) > 0:
    #                 record.current_cost += (record.old_amount - record.new_amount)
    #                 record.new_amount=record.old_amount

    # constraints on current cost and source line value
    # @api.constrains('source_line_ids')
    # def _amount_constraint(self):
    #     for record in self:
    #         if record.current_cost < record.old_amount :
    #             raise (_('amount in source lines must not be bigger than current value'))

    @api.model
    def create(self, values):
        values['name'] = self.env['ir.sequence'].next_by_code('asset_management.book_assets.BookAssets')
        record = super(BookAssets, self).create(values)
        if 'assignment_id' not in values:
            raise ValidationError(_('Assignment must be added in book (' + str(self.book_id.name) + ')'))
        if 'source_line_ids' not in values:
            raise ValidationError(_('Source line must be added to book (' + str(self.book_id.name) + ')'))

        for assign in record.assignment_id:
            assign.date_from = record.prorate_date
        return record

    #         record.compute_depreciation_board()

    @api.multi
    def write(self, values):
        old_gross_value = self.current_cost
        old_category = self.category_id

        old_assign = self.assignment_id.filtered(lambda x: not x.history_flag and not x.date_to and x.date_from)
        old = []
        for x in old_assign:
            if x.date_from < self.book_id.calendar_line_id.start_date:
                tag_ids = []
                for tag in x.depreciation_expense_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                values2 = {
                    'id': x.id,
                    'book_assets_id': self.id,
                    'depreciation_expense_account': x.depreciation_expense_account.id,
                    'responsible_id': x.responsible_id.id,
                    'location_id': x.location_id.id,
                    'comments': x.comments,
                    'depreciation_expense_analytic_account_id': x.depreciation_expense_analytic_account_id.id,
                    'depreciation_expense_analytic_tag_ids': tag_ids,
                    'percentage': x.percentage,
                    'date_from': x.date_from
                }
                old.append(values2)

        super(BookAssets, self).write(values)
        if not self.source_line_ids:
            raise ValidationError(_('Source line must be added to book'))

        new_assignment, assign_change_flag = self._create_assignment(old)

        if 'assign_change_flag' in values:
            if self.assign_change_flag:
                # self._create_assignment()
                self.assignment_id = new_assignment
                self.assign_change_flag = assign_change_flag

        if self.state == 'draft':
            if 'category_id' in values:
                if self.category_id != old_category:
                    self.asset_id.category_id = self.category_id.id
                    new_depreciation_expense_account = self.env['asset_management.category_books'].search(
                        [('book_id', '=', self.book_id.id),
                         ('category_id', '=', self.category_id.id)]).depreciation_expense_account
                    for assignment in self.assignment_id:
                        assignment.depreciation_expense_account = new_depreciation_expense_account
                        self.compute_depreciation_board()
            if 'current_cost' in values:
                self.compute_depreciation_board()

        elif self.state == 'open':
            for record in self:
                if 'current_cost' in values:
                    if not 'current_cost_from_retir' in values:
                        self.env['asset_management.transaction'].create({
                            'book_assets_id': record.id,
                            'asset_id': record.asset_id.id,
                            'book_id': record.book_id.id,
                            'category_id': record.category_id.id,
                            'trx_type': 'cost_adjustment',
                            'trx_date': datetime.today(),
                            'trx_details': 'Old Gross Value  Is: ' + str(
                                old_gross_value) + '\nNew Gross Vale Is:%s ' % self.current_cost,
                            'cost': self.current_cost,
                            'old_cost': old_gross_value
                        })
                        self.compute_depreciation_board()

                if 'category_id' in values:
                    if self.category_id != old_category:
                        new_depreciation_expense_account = self.env['asset_management.category_books'].search(
                            [('book_id', '=', self.book_id.id),
                             ('category_id', '=', self.category_id.id)]).depreciation_expense_account
                        for assignment in self.assignment_id:
                            assignment.depreciation_expense_account = new_depreciation_expense_account

                        record.env['asset_management.transaction'].create({
                            'book_assets_id': record.id,
                            'asset_id': record.asset_id.id,
                            'book_id': record.book_id.id,
                            'trx_type': 're_class',
                            'trx_date': datetime.today(),
                            'category_id': record.category_id.id,
                            'old_category': old_category.id,
                            'cost': self.current_cost,
                            'trx_details': 'old category : ' + old_category.name + '\nnew category : ' + record.category_id.name

                        })
                        self.compute_depreciation_board()

                if 'assignment_id' in values:
                    if not self.assign_change_flag:
                        responsable = []
                        location = []
                        for assignment in self.assignment_id:
                            if assignment.responsible_id:
                                responsable.append(assignment.responsible_id.name)
                            location.append(assignment.location_id.name)
                        self.env['asset_management.transaction'].create({
                            'book_assets_id': self.id,
                            'book_id': self.book_id.id,
                            'asset_id': self.asset_id.id,
                            'category_id': self.category_id.id,
                            'trx_type': 'transfer',
                            'cost': self.current_cost,
                            'trx_date': datetime.today(),
                            'trx_details': 'Responsible : ' + str(responsable) + '\nLocation : ' + str(location)

                            if responsable else 'Location : ' + str(location)
                        })

    def _create_assignment(self, old):
        self.ensure_one()
        new_assignment = []
        tag_ids = []
        if self.prorate_date >= self.book_id.calendar_line_id.start_date:
            new_assignment = [(2, line_id.id, False) for line_id in self.assignment_id]
            for assign in self.assignment_id:
                for tag in assign.depreciation_expense_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                vals = {
                    'book_assets_id': self.id,
                    'depreciation_expense_account': assign.depreciation_expense_account.id,
                    'responsible_id': assign.responsible_id.id,
                    'location_id': assign.location_id.id,
                    'date_from': self.prorate_date,
                    'comments': assign.comments,
                    'percentage': assign.percentage,
                    'depreciation_expense_analytic_account_id': assign.depreciation_expense_analytic_account_id.id,
                    'depreciation_expense_analytic_tag_ids': tag_ids
                }
                new_assignment.append((0, False, vals))

        elif self.prorate_date < self.book_id.calendar_line_id.start_date:
            new_assign = self.assignment_id.filtered(lambda x: not x.history_flag and not x.date_to)
            new_assignment = [(2, line_id.id, False) for line_id in new_assign]
            for assign in new_assign:
                for tag in assign.depreciation_expense_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                values = {
                    'book_assets_id': self.id,
                    'depreciation_expense_account': assign.depreciation_expense_account.id,
                    'responsible_id': assign.responsible_id.id,
                    'location_id': assign.location_id.id,
                    'comments': assign.comments,
                    'depreciation_expense_analytic_account_id': assign.depreciation_expense_analytic_account_id.id,
                    'depreciation_expense_analytic_tag_ids': tag_ids
                }
                depreciation_line = self.depreciation_line_ids.filtered(lambda x:x.move_check).sorted(key=lambda l: l.depreciation_date)[-1]
                next_dep_date = self.depreciation_line_ids.filtered(lambda x:x.sequence == depreciation_line.sequence+1)
                # for dep in depreciation_line:
                start_period_date = self.book_id.calendar_line_id.start_date
                if self.prorate_date <= depreciation_line.depreciation_date and not next_dep_date.depreciation_date < start_period_date:
                        if not assign.date_from:
                            values.update({
                                'date_from': self.book_id.calendar_line_id.start_date,
                                'percentage': assign.percentage,

                            })
                        else:
                            if assign.date_from < start_period_date:
                                # old_assign = self.env['asset_management.assignment'].search([('book_assets_id','=',self.id),('id','=',assign.id)])
                                # start_date = datetime.strptime(start_period_date, DF).date()
                                values.update({
                                    'date_from': start_period_date,
                                    'percentage': assign.percentage,
                                })
                                for ss in old:
                                    if ss.get('id') == assign.id:
                                        values2 = {
                                            'book_assets_id': self.id,
                                            'depreciation_expense_account': ss.get('depreciation_expense_account'),
                                            'responsible_id': ss.get('responsible_id'),
                                            'location_id': ss.get('location_id'),
                                            'comments': ss.get('comments'),
                                            'depreciation_expense_analytic_account_id': ss.get(
                                                'depreciation_expense_analytic_account_id'),
                                            'depreciation_expense_analytic_tag_ids': ss.get('tag_ids'),
                                            'date_to': start_period_date + relativedelta(days=-1),
                                            'history_flag': True,
                                            'date_from': ss.get('date_from'),
                                            'percentage': ss.get('percentage')
                                        }
                                        new_assignment.append((0, False, values2))
                            elif assign.date_from >= start_period_date:
                                values.update({
                                    'date_from': assign.date_from,
                                    'percentage': assign.percentage,
                                })

                        # break

                elif depreciation_line.depreciation_date >= self.prorate_date and next_dep_date.depreciation_date < start_period_date :
                        if not assign.date_from:
                            values.update({
                                'date_from': self.prorate_date,
                                'percentage': assign.percentage,
                            })
                        else:
                            values.update({
                                'date_from': assign.date_from,
                                'percentage': assign.percentage,
                            })
                        # break

                new_assignment.append((0, False, values))
        assign_change_flag = False
        return new_assignment, assign_change_flag

    @api.one
    @api.depends('date_in_service')
    def _compute_prorate_date(self):
        for record in self:
            if record.date_in_service:
                asset_date = record.date_in_service.replace(day=1)
                record.prorate_date = asset_date

    @api.onchange('book_id')
    def domain_for_book_id(self):
        if not self.asset_id:
            return

        category = self.asset_id.category_id
        if not category:
            warning = {
                'title': _('Warning!'),
                'message': _('You must first select a category!'),
            }
            return {'warning': warning}
        else:
            # if self.book_id:
            # self.category_id =self.asset_id.category_id.id
            # self.category_id = self._context.get('category_id')
            if self.book_id:
                vals = self.onchange_book_id_value(self.book_id.id)

                if vals:
                    for k, v in vals['value'].items():
                        setattr(self, k, v)

                cat = []
                category_domain = self.env['asset_management.category_books'].search(
                    [('book_id', '=', self.book_id.id)])
                for category in category_domain:
                    if category.category_id.active:
                        cat.append(category.category_id.id)
                return {'domain': {'category_id': [('id', 'in', cat)]
                                   }}
            else:
                res = []
                # default_book=self._context.get('default_book')
                book_domain = self.env['asset_management.category_books'].search(
                    [('category_id', '=', self._context.get('category_id'))])
                for book in book_domain:
                    if book.book_id.active:
                        res.append(book.book_id.id)

                return {'domain': {'book_id': [('id', 'in', res)]
                                   }}

    # get default value from CategoryBook
    # @api.onchange('book_id')
    # def _get_values_for_asset_book(self):
    #     if self.book_id:
    #         vals = self.onchange_book_id_value(self.book_id.id)
    #
    #         if vals:
    #             for k, v in vals['value'].items():
    #                 setattr(self, k, v)

    def onchange_book_id_value(self, book_id):
        if book_id:
            category_book = self.env['asset_management.category_books'].search(
                [('book_id', '=', book_id), ('category_id', '=', self.category_id.id)])
            return {
                'value': {
                    'method': category_book.depreciation_method,
                    'method_time': category_book.method_time,
                    'life_months': category_book.life_months,
                    'method_number': category_book.method_number,
                    # 'category_id':category_book.category_id.id,
                }
            }

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id:
            vals = self.onchange_category_id_value(self.category_id.id)

            if vals:
                for k, v in vals['value'].items():
                    setattr(self, k, v)

            res = []
            book_domain = self.env['asset_management.category_books'].search(
                [('category_id', '=', self.category_id.id)])
            for book in book_domain:
                if book.book_id.active:
                    res.append(book.book_id.id)
            return {'domain': {'book_id': [('id', 'in', res)]
                               }}

    # @api.onchange('category_id')
    # def _get_values(self):
    #     if self.category_id:
    #         vals = self.onchange_category_id_value(self.category_id.id)
    #
    #         if vals:
    #             for k, v in vals['value'].items():
    #                 setattr(self, k, v)

    def onchange_category_id_value(self, category_id):
        if category_id:
            category_book = self.env['asset_management.category_books'].search(
                [('book_id', '=', self.book_id.id), ('category_id', '=', category_id)])
            return {
                'value': {
                    'method': category_book.depreciation_method,
                    'method_time': category_book.method_time,
                    'life_months': category_book.life_months,
                    'method_number': category_book.method_number,
                    # 'category_id':category_book.category_id.id,
                    # 'end_date': category_book.end_date
                }
            }

    @api.constrains('original_cost')
    def _original_cost_cons(self):
        for rec in self:
            if rec.original_cost == 0:
                raise ValidationError(_('original cost  value must not be zero'))

    # called when asset is confirmed
    @api.multi
    def validate(self):
        if self.date_in_service > self.book_id.calendar_line_id.end_date:
            raise UserError(_('You can not confirm an asset with future date in service'))

        if not self.assignment_id and not self.source_line_ids:
            raise UserError(-("The fallowing fields should be entered in order to move to 'open' state "
                              "and be able to compute deprecation:"
                              "-\n Assignment"
                              "\n Source Line"))
        elif not self.assignment_id:
            raise UserError(_("You should assign the asset to a location"))
        elif not self.source_line_ids:
            raise ValidationError(_('Source line should be added'))
        self.write({'state': 'open'})

        if not self.asset_id.category_invisible:
            self.asset_id.write({'category_invisible': True})

        if not self.env['asset_management.transaction'].search(
                [('asset_id', '=', self.asset_id.id), ('book_id', '=', self.book_id.id),
                 ('trx_type', '=', 'addition')]):
            # if self.book_id.start_date > self.date_in_service:
            #     raise ValidationError(_("Date in service dose't belong to fiscal period change either the date in service or the fiscal period" ))
            self.env['asset_management.transaction'].create({
                'book_assets_id': self.id,
                'asset_id': self.asset_id.id,
                'book_id': self.book_id.id,
                'category_id': self.category_id.id,
                'trx_type': 'addition',
                'trx_date': self.book_id.calendar_line_id.start_date,
                'cost': self.original_cost,
                'trx_details': 'New Asset ' + self.asset_id.name + ' Is Added to the Book: ' + self.book_id.name +
                               '\n with cost = ' + str(self.original_cost)
            })
            responsable = []
            location = []
            for record in self.assignment_id:
                if record.responsible_id:
                    responsable.append(record.responsible_id.name)
                location.append(record.location_id.name)
                # if record.date_from:
                #     date=record.date_from
                # else:
                #     date='not specified'
            self.env['asset_management.transaction'].create({
                'book_assets_id': self.id,
                'book_id': self.book_id.id,
                'asset_id': self.asset_id.id,
                'category_id': self.category_id.id,
                'trx_type': 'transfer',
                'cost': self.current_cost,
                'trx_date': self.prorate_date,
                'trx_details': 'Responsible : ' + str(responsable) + '\nLocation : ' + str(location)

            })
            if self.asset_id.asset_type == 'capitalize':
                self.compute_depreciation_board()

    @api.multi
    def set_to_draft(self):
        self.write({'state': 'draft'})

    # compute percentage of all assignments
    @api.depends('assignment_id')
    def _modify_percentage(self):
        for record in self:
            for assignment in record.assignment_id:
                if not assignment.history_flag and not assignment.date_to:
                    record.percentage += assignment.percentage

    @api.constrains('assignment_id')
    def _checkpercentage(self):
        for record in self:
            # if float_compare(record.percentage, 100.00, precision_digits=2) != 0:
            if record.percentage != 100.00:
                raise ValidationError(_("Assignment does not equal a 100"))

    # compute residual value
    @api.one
    @api.depends('current_cost', 'salvage_value_amount', 'accumulated_value')
    # 'depreciation_line_ids.move_check', 'depreciation_line_ids.amount')
    def _amount_residual(self):
        if self.current_cost != 0:
            if self.salvage_value_amount > self.current_cost:
                raise ValidationError(_('Salvage Value must be less than Current Cost'))
            self.residual_value = self.current_cost - self.accumulated_value - self.salvage_value_amount

    # use in compute depreciation
    def _compute_board_undone_dotation_nb(self, depreciation_date):
        if self.method_time == 'end':
            if not self.end_date:
                raise ValidationError(_('End Date Is Required !'))
            end_date = datetime.strptime(self.end_date, DF).date()
            undone_dotation_number = 0
            while depreciation_date <= end_date:
                depreciation_date = date(depreciation_date.year, depreciation_date.month,
                                         depreciation_date.day) + relativedelta(months=+self.life_months)
                undone_dotation_number += 1
        else:
            if self.method_number == 0:
                raise ValidationError(_('Number of Depreciation Should Not be 0 '))
            undone_dotation_number = self.method_number
        return undone_dotation_number

    # use in compute depreciation
    def _compute_board_amount(self, sequence, residual_amount, amount_to_depr, undone_dotation_number,
                              posted_depreciation_line_ids):
        amount = 0
        if sequence == undone_dotation_number:
            amount = residual_amount
        else:
            if self.method == 'linear':
                amount = amount_to_depr / (undone_dotation_number - len(posted_depreciation_line_ids))
            elif self.method == 'degressive':
                amount = residual_amount * self.method_progress_factor
        return amount

    # use in compute depreciation
    @api.multi
    def compute_depreciation_board(self):
        self.ensure_one()
        # assign_in_book_asset=self.env['asset_management.assignment'].search([('asset_id','=',self.asset_id.id),('book_id','=',self.book_id.id)])
        if not self.assignment_id:
            raise UserError(_("You should assign the asset to a location"))
        elif self.date_in_service is False:
            raise UserError(_("Date in service must be entered"))
        elif not self.source_line_ids:
            raise ValidationError(_('Source line should be added'))
        elif self.method == 'degressive' and self.method_progress_factor < 0:
            raise ValidationError(_('Degressive Factor must be positive'))

        posted_depreciation_line_ids = self.depreciation_line_ids.filtered(lambda x: x.move_check).sorted(
            key=lambda l: l.depreciation_date)
        unposted_depreciation_line_ids = self.depreciation_line_ids.filtered(lambda x: not x.move_check)

        # Remove old unposted depreciation lines. We cannot use unlink() with One2many field
        commands = [(2, line_id.id, False) for line_id in unposted_depreciation_line_ids]

        if self.residual_value != 0.0:
            amount_to_depr = residual_amount = self.residual_value
            # if self.life_months >= 12:
            #     asset_date = datetime.strptime(self.date_in_service[:4] + '-01-01', DF).date()
            # else:
            asset_date = self.date_in_service.replace(day=1)
            # if we already have some previous validated entries, starting date isn't 1st January but last entry + method period
            if posted_depreciation_line_ids and posted_depreciation_line_ids[-1].depreciation_date:
                last_depreciation_date = fields.Date.from_string(posted_depreciation_line_ids[-1].depreciation_date)
                depreciation_date = last_depreciation_date + relativedelta(months=+self.life_months)
            else:
                depreciation_date = asset_date

            day = depreciation_date.day
            month = depreciation_date.month
            year = depreciation_date.year

            undone_dotation_number = self._compute_board_undone_dotation_nb(depreciation_date)

            for x in range(len(posted_depreciation_line_ids), undone_dotation_number):
                sequence = x + 1
                amount = self._compute_board_amount(sequence, residual_amount, amount_to_depr, undone_dotation_number,
                                                    posted_depreciation_line_ids)
                currency = self.book_id.company_id.currency_id
                amount = currency.round(amount)
                if float_is_zero(amount, precision_rounding=currency.rounding):
                    continue
                residual_amount -= amount
                vals = {
                    'amount': amount,
                    'asset_id': self.asset_id.id,
                    'book_id': self.book_id.id,
                    'sequence': sequence,
                    'name': (self.name or '') + '/' + str(sequence),
                    'remaining_value': residual_amount,
                    'depreciated_value': self.current_cost - (self.salvage_value_amount + residual_amount),
                    'depreciation_date': depreciation_date.strftime(DF),
                }
                commands.append((0, False, vals))
                # Considering Depr. Period as months
                depreciation_date = date(year, month, day) + relativedelta(months=+self.life_months)
                day = depreciation_date.day
                month = depreciation_date.month
                year = depreciation_date.year
        self.write({'depreciation_line_ids': commands})
        if self.current_cost_from_retir:
            self.current_cost_from_retir = False
        return True

    # open move.entry form view
    # asset_management.book_assets_list_action
    @api.multi
    def open_entries(self):
        move_ids = []
        for asset in self:
            for depreciation_line in asset.depreciation_line_ids:
                if depreciation_line.move_id:
                    move_ids.append(depreciation_line.move_id.id)
        return {
            'name': _('Journal Entries'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'account.move',
            'view_id': False,
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', move_ids)],
        }

    # number of generated entries
    @api.multi
    @api.depends('depreciation_line_ids.move_id')
    def _asset_entry_count(self):
        for asset in self:
            res = self.env['asset_management.depreciation'].search_count(
                [('asset_id', '=', asset.asset_id.id), ('book_id', '=', asset.book_id.id), ('move_id', '!=', False)])
            asset.entry_count = res or 0

    # # get default value from CategoryBook
    #     @api.onchange('book_id')
    #     def onchange_book_id(self):
    #         # self.category_id = self.asset_id.category_id.id
    #         vals = self.onchange_book_id_value(self.book_id.id)
    #         # We cannot use 'write' on an object that doesn't exist yet
    #         if vals:
    #             for k, v in vals['value'].items():
    #                 setattr(self, k, v)
    #
    #
    #     def onchange_book_id_value(self,book_id):
    #         if book_id:
    #             category_book = self.env['asset_management.category_books'].search([('book_id', '=', book_id),('category_id', '=', self._context.get('category_id'))])
    #             return{
    #                 'value' : {
    #                 'method': category_book.depreciation_method,
    #                 'method_time':category_book.method_time,
    #                 'life_months':category_book.life_months,
    #                 'method_number':category_book.method_number,
    #                 # 'category_id':category_book.category_id.id,
    #                 'end_date':category_book.end_date
    #                     }
    #                 }

    # to hide the depreciation compute button
    @api.depends('depreciation_line_ids')
    def _depreciation_line_length(self):
        for record in self:
            posted_depreciation_line_ids = self.depreciation_line_ids.filtered(lambda x: x.move_check)
            record.depreciation_line_length = len(posted_depreciation_line_ids)

    # compute percentage for salvage value
    @api.one
    @api.depends('salvage_value_type', 'salvage_value')
    def _compute_salvage_value_amount(self):
        for record in self:
            if record.salvage_value_type == 'amount':
                record.salvage_value_amount = record.salvage_value
            elif record.salvage_value_type == 'percentage':
                record.salvage_value_amount = (record.salvage_value * record.current_cost) / 100

    # open book asset form view
    @api.multi
    def move_to_book_asset(self):
        # view_id = self.env.ref('asset_management.book_assets_form_view').id
        return {
            'type': 'ir.actions.act_window',
            'name': _(' Asset In Book'),
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'asset_management.book_assets',
            'res_id': self.id,
            'target': 'current',
        }

    @api.multi
    def unlink(self):
        for record in self:
            raise ValidationError(_('Asset can not be deleted '))
        super(BookAssets, self).unlink()

    # @api.multi
    # def delete_source(self):
    #     text = 'Are you sure you want to delete a source line'
    #     value = self.env['asset_management.confirmation_wizard'].sudo().create({'text': text,
    #                                                                  })
    #     return {
    #                 'type': 'ir.actions.act_window',
    #                 'name': _('Warning'),
    #                 'view_type': 'form',
    #                 'view_mode': 'form',
    #                 'res_model': 'asset_management.confirmation_wizard',
    #                 'res_id': value.id,
    #                 'target': 'new',
    #                 'view_id': self.env.ref('asset_management.confirmation_wizard_form', False).id,
    #                 'context': {'active_id':self.id,
    #                             }
    #     }
    #


class Assignment(models.Model):
    _name = 'asset_management.assignment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Assignment", readonly='True', index=True)
    book_assets_id = fields.Many2one('asset_management.book_assets', on_delete='cascade')
    book_id = fields.Many2one("asset_management.book", string="Book", on_delete='cascade', compute="_get_book_name",
                              track_visibility='always')
    asset_id = fields.Many2one("asset_management.asset", string="Asset", on_delete='cascade', compute="_get_asset_name",
                               track_visibility='always')
    depreciation_expense_account = fields.Many2one('account.account', on_delete='set_null', required=True,
                                                   domain=[('user_type_id', '=', 'Depreciation')],
                                                   track_visibility='onchange')
    responsible_id = fields.Many2one('hr.employee', on_delete='set_null', track_visibility='onchange')
    location_id = fields.Many2one('asset_management.location', required=True, domain=[('active', '=', True)],
                                  track_visibility='onchange')
    history_flag = fields.Boolean(defult=False, readonly=True, track_visibility='onchange')
    date_to = fields.Date(track_visibility='onchange', readonly=True)
    date_from = fields.Date(track_visibility='onchange', readonly=True)
    comments = fields.Text(track_visibility='onchange')
    percentage = fields.Float(default=100, track_visibility='onchange')
    depreciation_expense_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                                               track_visibility='onchange')
    depreciation_expense_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                                             track_visibility='onchange')

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(Assignment, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('book_one2many_view'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    @api.onchange('book_id')
    def _dep_expense_domain(self):
        for record in self:
            return {'domain': {'depreciation_expense_account': [('company_id', '=', record.book_id.company_id.id)],
                               'depreciation_expense_analytic_account_id': [
                                   ('company_id', '=', record.book_id.company_id.id)]

                               }}

    @api.constrains('percentage')
    def _check_valid_percentage(self):
        for record in self:
            if not record.percentage < 101.00 and not record.percentage > 0.00:
                raise ValidationError(_("Invalid value"))

    # @api.constrains('transfer_date')
    # def _transfer_date_constrain(self):
    #     for record in self:
    #         transfer_date=str((record.transfer_date,DF).year)
    #         if  record.transfer_date < record.book_assets_id.date_in_service:
    #             raise ValidationError(_('Transfer Date must not be before Date In Service'))
    #
    #         elif  transfer_date != record.book_id.fiscal_year:
    #                 raise ValidationError(_('Transfer Date must be in the fiscal year '+record.book_id.fiscal_year))

    # get default value from CategoryBook
    @api.onchange('book_id')
    def onchange_responsible_id(self):
        # if not self.book_assets_id:
        #     return

        category_book = self.env['asset_management.category_books'].search(
            [('book_id', '=', self.book_id.id), ('category_id', '=', self.book_assets_id.category_id.id)])
        tag_ids = []
        for tag in category_book.depreciation_expense_analytic_tag_ids:
            tag_ids.append((4, tag.id, 0))
        value = {
            'depreciation_expense_account': category_book.depreciation_expense_account,
            'depreciation_expense_analytic_account_id': category_book.depreciation_expense_analytic_account_id,
            'depreciation_expense_analytic_tag_ids': tag_ids
        }
        for k, v in value.items():
            setattr(self, k, v)

    # creat transaction record when adding a new assignment and location
    # @api.model
    # def create(self, values):
    #     values['name']=self.env['ir.sequence'].next_by_code('asset_management.assignment.Assignment')
    #     record=super(Assignment, self).create(values)
    #     if record.book_assets_id.state == 'open':
    #         # if record.transfer_date:
    #         #     date = record.transfer_date
    #         # else:
    #         #     date = 'not specified'
    #         record.env['asset_management.transaction'].create({
    #             'book_assets_id':record.book_assets_id.id,
    #             'book_id':record.book_id.id,
    #             'asset_id': record.asset_id.id,
    #             'category_id': record.book_assets_id.category_id.id,
    #             'trx_type': 'transfer',
    #             'trx_date': datetime.today(),
    #             'trx_details':'Responsible : '+ record.responsible_id.name + '\nLocation : '+ record.location_id.name
    #                                 if record.responsible_id else 'Location : '+record.location_id.name
    #         })
    #     return record

    @api.depends('book_assets_id')
    def _get_asset_name(self):
        for rec in self:
            rec.asset_id = rec.book_assets_id.asset_id.id
            return rec.asset_id

    @api.depends('book_assets_id')
    def _get_book_name(self):
        for rec in self:
            rec.book_id = rec.book_assets_id.book_id.id
            return rec.book_id

    @api.multi
    def unlink(self):
        for record in self:
            if record.book_assets_id.state != 'close':
                if record.history_flag or record.date_to:
                    raise ValidationError(_('Assignment history can not be deleted '))
            else:
                raise ValidationError(_('Asset is closed'))
        super(Assignment, self).unlink()


class SourceLine(models.Model):
    _name = 'asset_management.source_line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Source Line Number", readonly=True, index=True)
    book_assets_id = fields.Many2one('asset_management.book_assets', on_delete='cascade')
    asset_id = fields.Many2one('asset_management.asset', on_delete='cascade', compute='_get_asset_name',
                               track_visibility='always')
    book_id = fields.Many2one('asset_management.book', on_delete='cascade', compute='_get_book_name',
                              track_visibility='always')
    source_type = fields.Selection(
        [('invoice', 'Invoice'), ('miscellaneous', 'Miscellaneous')
         ], default='invoice', required=True, track_visibility='onchange'
    )
    invoice_id = fields.Many2one("account.invoice", string="invoice", on_delete='cascade', track_visibility='onchange')
    invoice_line_ids = fields.Many2one("account.invoice.line", string="Invoice Line", on_delete='cascade',
                                       track_visibility='onchange')
    amount = fields.Float('Amount', compute="_get_price_from_invoice", track_visibility='onchange')
    invoice_id_m_type = fields.Char('Invoice', track_visibility='onchange')
    invoice_line_ids_m_type = fields.Char('Invoice Line', track_visibility='onchange')
    amount_m_type = fields.Float('Amount', track_visibility='onchange')
    description = fields.Text(track_visibility='onchange')

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(SourceLine, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('book_one2many_view'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    @api.model
    def create(self, values):
        values['name'] = self.env['ir.sequence'].next_by_code('asset_management.source_line.SourceLine')
        return super(SourceLine, self).create(values)

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            invoice_line = []
            for line in self.invoice_id.invoice_line_ids:
                invoice_line.append(line.id)
            return {'domain': {'invoice_line_ids': [('id', 'in', invoice_line)]
                               }}

    @api.one
    @api.depends('invoice_id', 'invoice_line_ids')
    def _get_price_from_invoice(self):
        for record in self:
            record.amount = record.invoice_line_ids.price_unit

    @api.depends('book_assets_id')
    def _get_asset_name(self):
        for rec in self:
            rec.asset_id = rec.book_assets_id.asset_id.id
            return rec.asset_id

    @api.depends('book_assets_id')
    def _get_book_name(self):
        for rec in self:
            rec.book_id = rec.book_assets_id.book_id.id
            return rec.book_id

    @api.multi
    def unlink(self):
        for line in self:
            if line.book_assets_id.state != 'close':
                if line.source_type == 'invoice':
                    if line.book_assets_id.net_book_value - line.amount < 0:
                        raise ValidationError(_('You can not delete a source line from ' + line.book_id.name))
                    elif line.book_assets_id.net_book_value - line.amount == 0:
                        raise ValidationError(_(
                            'Net book value equals 0 ,add source line in Miscellaneous type with the required amount '))
                elif line.source_type == 'miscellaneous':
                    if line.book_assets_id.net_book_value - line.amount_m_type < 0:
                        raise ValidationError(_('You can not delete a source line from ' + line.book_id.name))
                    elif line.book_assets_id.net_book_value - line.amount_m_type == 0:
                        raise ValidationError(_(
                            'Net book value equals 0 ,add source line in Miscellaneous type with the required amount '))

            else:
                raise ValidationError(_('Asset is closed'))
                # else:
            #     text = 'Are you sure you want to delete a source line'
            #     value = self.env['asset_management.confirmation_wizard'].sudo().create({'text': text,
            #                                                                  })
            #     return {
            #                 'type': 'ir.actions.act_window',
            #                 'name': _('Warning'),
            #                 'view_type': 'form',
            #                 'view_mode': 'form',
            #                 'res_model': 'asset_management.confirmation_wizard',
            #                 'res_id': value.id,
            #                 'target': 'new',
            #                 'view_id': self.env.ref('asset_management.confirmation_wizard_form', False).id,
            #                 'context': {'active_id':self.id,
            #                             }
            #
            #             }

        return super(SourceLine, self).unlink()


class Depreciation(models.Model):
    _name = 'asset_management.depreciation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Depreciation Number", readonly=True, index=True)
    book_assets_id = fields.Many2one('asset_management.book_assets', on_delete='cascade')
    asset_id = fields.Many2one('asset_management.asset', on_delete='cascade', track_visibility='always')
    book_id = fields.Many2one('asset_management.book', on_delete='cascade', track_visibility='always')
    sequence = fields.Integer(required=True, track_visibility='onchange')
    amount = fields.Float(string='Current Depreciation', digits=0, track_visibility='onchange')
    remaining_value = fields.Float(string='Next Period Depreciation', digits=0, required=True,
                                   track_visibility='onchange')
    depreciated_value = fields.Float(string='Cumulative Depreciation', required=True, track_visibility='onchange')
    depreciation_date = fields.Date('Depreciation Date', index=True, track_visibility='onchange')
    move_id = fields.Many2one('account.move', string='Depreciation Entry', track_visibility='onchange')
    move_check = fields.Boolean(compute='_get_move_check', string='Linked (Account)', track_visibility='always',
                                store=True)
    move_posted_check = fields.Boolean(compute='_get_move_posted_check', string='Posted', track_visibility='always',
                                       store=True)
    parent_state = fields.Selection(related="book_assets_id.state", string='State of Asset')
    dep_run_process_id = fields.Many2one('asset_management.deprunprocess', on_delete='cascade',
                                         track_visibility='onchange')
    period_id = fields.Many2one('asset_management.calendar_line', track_visibility='onchange')

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(Depreciation, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('asset_with_one2many') or self._context.get('book_one2many_view'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    @api.multi
    @api.depends('move_id')
    def _get_move_check(self):
        for line in self:
            # line.book_assets_id.accumulated_value = line.depreciated_value
            line.move_check = bool(line.move_id)

    @api.multi
    @api.depends('move_id.state')
    def _get_move_posted_check(self):
        for line in self:
            line.move_posted_check = True if line.move_id and line.move_id.state == 'posted' else False

    # generate entries in account.move
    @api.multi
    def create_move(self, post_move=True):
        created_moves = self.env['account.move']
        prec = self.env['decimal.precision'].precision_get('Account')
        # current_currency = self.env['res.company'].search([('id','=',1)])[0].currency_id
        if self.depreciation_date > self.book_id.calendar_line_id.end_date:
            raise ValidationError(_('You can not create Entries for Line with Future Date'))
        journal_id = self.env['asset_management.category_books'].search(
            [('book_id', '=', self.book_id.id), ('category_id', '=', self.book_assets_id.category_id.id)]).journal_id
        tag_ids = []
        for line in self:
            if line.move_id:
                raise UserError(
                    _('This depreciation is already linked to a journal entry! Please post or delete it.'))
            company_currency = line.book_id.company_id.currency_id
            current_currency = line.asset_id.currency_id
            # depreciation_date = self.env.context.get('depreciation_date') or line.depreciation_date or fields.Date.context_today(self)
            move_to_jl_date = line.book_id.calendar_line_id.end_date
            category_books = line.env['asset_management.category_books'].search(
                [('book_id', '=', self.book_id.id), ('category_id', '=', self.book_assets_id.category_id.id)])[0]
            accumulated_depreciation_account = category_books.accumulated_depreciation_account
            # depreciation_expense_account=line.env['asset_management.assignment'].search([('asset_id','=',self.asset_id.id),('book_id','=',self.book_id.id)]).depreciation_expense_account
            partner_id = line.env['asset_management.source_line'].search([('asset_id', '=', self.asset_id.id)])[
                0].invoice_id.partner_id
            if partner_id is None:
                raise ValidationError(_("Source Line must be entered"))
            asset_name = line.asset_id.name + ' (%s/%s)' % (line.sequence, len(line.asset_id.depreciation_line_ids))
            amount = current_currency.with_context(date=move_to_jl_date).compute(line.amount, company_currency)
            for tag in category_books.accumulated_depreciation_analytic_tag_ids:
                tag_ids.append((4, tag.id, 0))
            move_line_1 = {
                'name': asset_name,
                'account_id': accumulated_depreciation_account.id,
                'debit': 0.0 if float_compare(amount, 0.0, precision_digits=prec) > 0 else -amount,
                'credit': amount if float_compare(amount, 0.0, precision_digits=prec) > 0 else 0.0,
                'journal_id': journal_id.id,
                'partner_id': partner_id.id,
                'currency_id': company_currency != current_currency and current_currency.id or False,
                'amount_currency': company_currency != current_currency and - 1.0 * line.amount or 0.0,
                'analytic_account_id': category_books.accumulated_depreciation_analytic_account_id.id if category_books.accumulated_depreciation_analytic_account_id else False,
                'analytic_tag_id': tag_ids
            }
            move_vals = {
                'ref': line.asset_id.name,
                'date': move_to_jl_date or False,
                'journal_id': journal_id.id,
                'line_ids': [(0, 0, move_line_1)],
            }
            assignment_in_book = line.env['asset_management.assignment'].search(
                [('book_assets_id', '=', line.book_assets_id.id), ('date_to', '=', False)])
            for assignment in assignment_in_book:
                amount = (line.amount * assignment.percentage) / 100.00
                # amount = current_currency.with_context(date=depreciation_date).compute(amount,company_currency)
                depreciation_expense_account = assignment.depreciation_expense_account.id
                for tag in assignment.depreciation_expense_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_2 = {
                    'name': asset_name,
                    'account_id': depreciation_expense_account,
                    'credit': 0.0 if float_compare(amount, 0.0, precision_digits=prec) > 0 else -amount,
                    'debit': amount if float_compare(amount, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'partner_id': partner_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * line.amount or 0.0,
                    'analytic_account_id': assignment.depreciation_expense_analytic_account_id.id if assignment.depreciation_expense_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                move_vals['line_ids'].append((0, 0, move_line_2))
            move = self.env['account.move'].create(move_vals)
            line.write({'move_id': move.id, 'move_check': True})
            line.book_assets_id.accumulated_value = line.depreciated_value
            created_moves |= move

            return [x.id for x in created_moves]

    @api.multi
    def post_lines_and_close_asset(self):
        # we re-evaluate the assets to determine whether we can close them
        for line in self:
            # line.log_message_when_posted()
            asset = line.asset_id
            book = line.book_id
            book_asset = line.env['asset_management.book_assets'].search(
                [('asset_id', '=', asset.id), ('book_id', '=', book.id)])
            residual_value = book_asset[0].residual_value
            current_currency = self.env['res.company'].search([('id', '=', 1)])[0].currency_id
            if current_currency.is_zero(residual_value):
                # asset.message_post(body=_("Document closed."))
                book_asset.write({'state': 'close'})

    @api.multi
    def unlink(self):
        for record in self:
            if record.move_check:
                if record.asset_id.source_line_id.source_type == 'po':
                    msg = _("You cannot delete posted depreciation lines.")
                else:
                    msg = _("You cannot delete posted installment lines.")
                raise UserError(msg)
        return super(Depreciation, self).unlink()

    @api.model
    def create(self, values):
        values['name'] = self.env['ir.sequence'].next_by_code('asset_management.depreciation.Depreciation')
        return super(Depreciation, self).create(values)


class Retirement(models.Model):
    _name = 'asset_management.retirement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Retirement Number", readonly=True, index=True)
    book_assets_id = fields.Many2one('asset_management.book_assets', on_delete='cascade', compute="_get_book_assets_id")
    book_id = fields.Many2one('asset_management.book', on_delete='cascade', required=True,
                              domain=[('active', '=', True)], track_visibility='always')
    asset_id = fields.Many2one('asset_management.asset', on_delete='cascade', required=True, track_visibility='always')
    retire_date = fields.Date(string='Retire Date', default=lambda self: date.today(), track_visibility='onchange')
    comments = fields.Text(string="Comments", track_visibility='onchange')
    gain_loss_amount = fields.Float(track_visibility='onchange', readonly=True)
    proceeds_of_sale = fields.Float(track_visibility='onchange')
    cost_of_removal = fields.Float(track_visibility='onchange')
    partner_id = fields.Many2one(comodel_name="res.partner", string="Sold To", track_visibility='onchange')
    check_invoice = fields.Char(track_visibility='onchange')
    retired_cost = fields.Float(required=True, track_visibility='onchange')
    current_asset_cost = fields.Float(string="Current Cost", readonly=True, track_visibility='onchange')
    net_book_value = fields.Float(string="Original Net Book Value", track_visibility='onchange', readonly=True)
    accumulated_value = fields.Float(track_visibility='onchange', readonly=True)
    retirement_type_id = fields.Many2one('asset_management.retirement_type', on_delete="set_null",
                                         track_visibility='onchange')
    prorate_date = fields.Date(string='Prorate Date', compute="_compute_prorate_date", track_visibility='onchange')
    state = fields.Selection([('draft', 'Draft'), ('complete', 'Complete'), ('reinstall', 'Reinstall')],
                             'Status', required=True, copy=False, default='draft', track_visibility='onchange')

    # jl_is_posted=fields.Boolean(compute="_get_jl_posted_check")

    # @api.depends('asset_id','book_id')
    # def _get_jl_posted_check(self):
    #     for record in self:
    #         retirement_jl=record.env['asset_management.transaction'].search([('retirement_id','=',record.id),
    #                                                                          ('asset_id','=',record.asset_id.id),('book_id','=',record.book_id.id)]).move_id
    #         if retirement_jl.state == 'posted':
    #             record.jl_is_posted = True

    @api.one
    @api.depends('retire_date')
    def _compute_prorate_date(self):
        for record in self:
            if record.retire_date:
                asset_date = record.retire_date.replace(day=1)
                record.prorate_date = asset_date

    @api.constrains('retire_date')
    def _retire_date_check(self):
        if self.retire_date > self.book_id.calendar_line_id.end_date or self.retire_date < self.book_id.calendar_line_id.start_date:
            raise ValidationError(
                _("Retirement date must be in fiscal period from " + self.book_id.calendar_line_id.start_date + " to "
                  + self.book_id.calendar_line_id.end_date +
                  "\nchange the date in service or the fiscal period"))

    @api.onchange('book_id')
    def _asset_in_book(self):
        if self.book_id:
            res = []
            asset_in_book = self.env['asset_management.book_assets'].search([('book_id', '=', self.book_id.id)])
            for asset in asset_in_book:
                if asset.state == 'open':
                    res.append(asset.asset_id.id)

            return {'domain': {'asset_id': [('id', 'in', res)]
                               }}

    @api.depends('book_id', 'asset_id')
    def _get_book_assets_id(self):
        for record in self:
            if record.book_id and record.asset_id:
                asset_book = record.env['asset_management.book_assets'].search(
                    [('asset_id', '=', record.asset_id.id), ('book_id', '=', record.book_id.id)])
                record.book_assets_id = asset_book.id

    @api.onchange('book_id', 'asset_id')
    def _get_asset_cost(self):
        self.test = False
        if self.book_id and self.asset_id:
            values = self.get_values_from_book_asset(self.book_id.id, self.asset_id.id)
            if values:
                for k, v in values['value'].items():
                    setattr(self, k, v)

    def get_values_from_book_asset(self, book_id, asset_id):
        if book_id and asset_id:
            asset_value = self.env['asset_management.book_assets'].search(
                [('asset_id', '=', self.asset_id.id), ('book_id', '=', self.book_id.id)])
            return {'value':
                        {'current_asset_cost': asset_value.current_cost,
                         'accumulated_value': asset_value.accumulated_value,
                         'net_book_value': asset_value.net_book_value,
                         'retired_cost': asset_value.net_book_value}
                    }

    @api.onchange('retired_cost', 'current_asset_cost')
    def _compute_gain_lost(self):
        if self.retired_cost and self.current_asset_cost:
            self.gain_loss_amount = self.retired_cost - self.accumulated_value

    @api.multi
    def required_computation(self):
        for record in self:
            if record.retired_cost == 0:
                raise ValidationError(_('Retired cost must be entered.'))
            # current_cost=record.book_assets_id.current_cost
            # net_book_value=record.book_assets_id.net_book_value
            record.gain_loss_amount = record.retired_cost - record.accumulated_value
            if record.retired_cost <= record.accumulated_value:
                net_book = (record.current_asset_cost - record.retired_cost) - (
                        record.accumulated_value - record.retired_cost)
            elif record.retired_cost > record.accumulated_value or record.retired_cost == record.current_asset_cost:
                net_book = record.current_asset_cost - record.retired_cost
            # record.current_asset_cost=current_cost
            if net_book < 0:
                net_book = 0.0
            record.book_assets_id.write({'current_cost': net_book,
                                         'current_cost_from_retir': True,
                                         'accumulated_value': 0.0})
            record.book_assets_id.compute_depreciation_board()

    @api.multi
    def reinstall(self):
        trx = self.env['asset_management.transaction'].search([('retirement_id', '=', self.id)])
        journal_entries = trx.move_id
        journal_id = journal_entries.journal_id
        date = datetime.today()
        reserved_jl = self.env['account.move'].browse(journal_entries.id).reverse_moves(date, journal_id)
        if reserved_jl:
            self.state = 'reinstall'
            return {
                'name': _('Reinstall move'),
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'tree,form',
                'res_model': 'account.move',
                'domain': [('id', 'in', reserved_jl)],
            }

    @api.model
    def create(self, values):
        values['name'] = self.env['ir.sequence'].next_by_code('asset_management.retirement.Retirement')
        res = super(Retirement, self).create(values)
        res.required_computation()
        if res.retired_cost == res.current_asset_cost:
            res.env['asset_management.transaction'].create({
                'book_assets_id': res.book_assets_id.id,
                'asset_id': res.asset_id.id,
                'book_id': res.book_id.id,
                'category_id': res.book_assets_id.category_id.id,
                'trx_type': 'full_retirement',
                'trx_date': res.retire_date,
                'retirement_id': res.id,
                'trx_details': 'A full retirement has occur for asset (' + str(res.asset_id.name) + ') on book (' + str(
                    res.book_id.name) + ')'
            })
        else:
            res.env['asset_management.transaction'].create({
                'book_assets_id': res.book_assets_id.id,
                'asset_id': res.asset_id.id,
                'book_id': res.book_id.id,
                'category_id': res.book_assets_id.category_id.id,
                'trx_type': 'partial_retirement',
                'trx_date': res.retire_date,
                'retirement_id': res.id,
                'trx_details': 'A partial retirement has occur for asset (' + str(
                    res.asset_id.name) + ') on book (' + str(res.book_id.name) + ')'

            })
        return res

    @api.multi
    def unlink(self):
        for record in self:
            raise ValidationError(_('Retirement can not be deleted '))
        super(Retirement, self).unlink()


class CategoryBooks(models.Model):
    _name = 'asset_management.category_books'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Category Books Num", index=True)
    category_id = fields.Many2one('asset_management.category', readonly=True, on_delete='cascade', string='Category',
                                  track_visibility='always')
    book_id = fields.Many2one('asset_management.book', on_delete='cascade', string='Book Num', required=True,
                              domain=[('active', '=', True)], track_visibility='always')
    asset_cost_account = fields.Many2one('account.account', on_delete='set_null', required=True,
                                         domain=[('user_type_id', '=', 'Fixed Assets')], track_visibility='onchange')
    asset_clearing_account = fields.Many2one('account.account', on_delete='set_null', required=True,
                                             domain=[('user_type_id', '=', 'Fixed Assets')],
                                             track_visibility='onchange')
    depreciation_expense_account = fields.Many2one('account.account', on_delete='set_null', required=True,
                                                   domain=[('user_type_id', '=', 'Depreciation')],
                                                   track_visibility='onchange')
    accumulated_depreciation_account = fields.Many2one('account.account', on_delete='set_null', required=True,
                                                       domain=[('user_type_id', '=', 'Fixed Assets')],
                                                       track_visibility='onchange')
    book_with_cate = fields.Boolean(related='book_id.book_with_cate')
    group_entries = fields.Boolean(deafult=True, track_visibility='onchange')
    journal_id = fields.Many2one('account.journal', string='Journal', required=True, track_visibility='onchange')
    depreciation_method = fields.Selection([('linear', 'Linear'), ('degressive', 'Degressive')], default='linear',
                                           track_visibility='onchange')
    life_months = fields.Integer(required=True, track_visibility='onchange')
    method_time = fields.Selection([('number', 'Number of Entries'), ('end', 'Ending Date')], string='Time Method',
                                   required=True, default='number', track_visibility='onchange',
                                   help="Choose the method to use to compute the dates and number of entries.\n"
                                        "  * Number of Entries: Fix the number of entries and the time between 2 depreciations.\n"
                                        "  * Ending Date: Choose the time between 2 depreciations and the date the depreciations won't go beyond.")
    method_number = fields.Integer(string='Number of Depreciation',
                                   help="The number of depreciations needed to depreciate your asset",
                                   track_visibility='onchange')
    _sql_constraints = [
        ('unique_book_id_on_cat', 'UNIQUE(book_id,category_id)', 'Category is already added to this book')
    ]
    asset_cost_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                                     track_visibility='onchange')
    asset_cost_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                                   track_visibility='onchange')
    asset_clearing_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                                         track_visibility='onchange')
    asset_clearing_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                                       track_visibility='onchange')
    depreciation_expense_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                                               track_visibility='onchange')
    depreciation_expense_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                                             track_visibility='onchange')
    accumulated_depreciation_analytic_account_id = fields.Many2one('account.analytic.account',
                                                                   string='Analytic Account',
                                                                   track_visibility='onchange')
    accumulated_depreciation_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                                                 track_visibility='onchange')

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(CategoryBooks, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('category_one2many_view'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    @api.model
    def create(self, values):
        values['name'] = self.env['ir.sequence'].next_by_code('asset_management.category_books.CategoryBooks')
        return super(CategoryBooks, self).create(values)

    @api.onchange('book_id')
    def onchange_book_id(self):
        if self.book_id:
            self.book_with_cate = True
            return {'domain': {'asset_cost_account': [('company_id', '=', self.book_id.company_id.id),
                                                      ('user_type_id', '=', 'Fixed Assets')],
                               'asset_clearing_account': [('company_id', '=', self.book_id.company_id.id),
                                                          ('user_type_id', '=', 'Fixed Assets')],
                               'depreciation_expense_account': [('company_id', '=', self.book_id.company_id.id),
                                                                ('user_type_id', '=', 'Depreciation')],
                               'accumulated_depreciation_account': [('company_id', '=', self.book_id.company_id.id),
                                                                    ('user_type_id', '=', 'Fixed Assets')],
                               'asset_cost_analytic_account_id': [('company_id', '=', self.book_id.company_id.id)],
                               'asset_clearing_analytic_account_id': [('company_id', '=', self.book_id.company_id.id)],
                               'depreciation_expense_analytic_account_id': [
                                   ('company_id', '=', self.book_id.company_id.id)],
                               'accumulated_depreciation_analytic_account_id': [
                                   ('company_id', '=', self.book_id.company_id.id)],
                               'journal_id': [('company_id', '=', self.book_id.company_id.id)]
                               }}

    @api.multi
    def unlink(self):
        for record in self:
            book_with_asset = record.env['asset_management.book_assets'].search([('book_id', '=', self.book_id.id)])[0]
            if book_with_asset:
                raise ValidationError(_(
                    'You can not delete a book contains assets'))
        return super(CategoryBooks, self).unlink()


class Transaction(models.Model):
    _name = 'asset_management.transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(string="Transaction Number", readonly=True, index=True)
    book_assets_id = fields.Many2one('asset_management.book_assets', on_delte='cascade')
    asset_id = fields.Many2one('asset_management.asset', on_delete='cascade', string="Asset", track_visibility='always')
    book_id = fields.Many2one('asset_management.book', on_delete='cascade', string="Book", track_visibility='always')
    category_id = fields.Many2one("asset_management.category", string="Category", on_delete='cascade',
                                  track_visibility='always')
    trx_type = fields.Selection(
        [
            ('addition', 'Addition'),
            ('re_class', 'Re_Class'),
            ('transfer', 'Transfer'),
            ('cost_adjustment', 'Cost Adjustment'),
            ('full_retirement', 'Full Retirement'),
            ('partial_retirement', 'Partial Retirement')
        ], string='Transaction Type', track_visibility='onchange'
    )
    trx_date = fields.Date('Transaction Date', track_visibility='onchange')
    trx_details = fields.Text('Transaction Details', track_visibility='onchange')
    old_category = fields.Many2one("asset_management.category", string=" Old Category", on_delete='cascade',
                                   track_visibility='onchange')
    move_id = fields.Many2one('account.move', string='Transaction Entry', track_visibility='onchange')
    move_check = fields.Boolean(compute='_get_move_check', string='Linked (Account)', track_visibility='always',
                                store=True)
    move_posted_check = fields.Boolean(compute='_get_move_posted_check', string='Posted', track_visibility='always',
                                       store=True)
    cost = fields.Float('Current Value', track_visibility='onchange')
    old_cost = fields.Float('Old Current Value', track_visibility='onchange')
    retirement_id = fields.Many2one('asset_management.retirement', track_visibility='onchange')

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(Transaction, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('asset_with_one2many') or self._context.get('book_one2many_view'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    @api.multi
    @api.depends('move_id')
    def _get_move_check(self):
        for line in self:
            line.move_check = bool(line.move_id)

    @api.multi
    @api.depends('move_id.state')
    def _get_move_posted_check(self):
        for line in self:
            line.move_posted_check = True if line.move_id and line.move_id.state == 'posted' else False

    @api.model
    def create(self, vals):
        vals['name'] = self.env['ir.sequence'].next_by_code('asset_management.transaction.Transaction')
        record = super(Transaction, self).create(vals)
        return record

    @api.multi
    def create_trx_move(self):
        prec = self.env['decimal.precision'].precision_get('Account')
        created_moves = self.env['account.move']
        tag_ids = []
        for line in self:
            trx_name = line.name
            current_currency = line.asset_id.currency_id
            company_currency = line.book_id.company_id.currency_id
            gross_value = line.env['asset_management.book_assets'].search(
                [('asset_id', '=', line.asset_id.id), ('book_id', '=', line.book_id.id)]).current_cost
            if line.trx_type == 'addition':
                # journal_id = self.env['asset_management.category_books'].search(
                #     [('book_id', '=', self.book_id.id), ('category_id', '=', self.category_id.id)]).journal_id
                accounts = line.env['asset_management.category_books'].search(
                    [('book_id', '=', line.book_id.id), ('category_id', '=', line.category_id.id)])
                journal_id = accounts.journal_id
                asset_cost_account = accounts.asset_cost_account.id
                asset_clearing_account = accounts.asset_clearing_account.id
                for tag in accounts.asset_clearing_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                # credit
                move_line_1 = {
                    'name': trx_name,
                    'account_id': asset_clearing_account,
                    'debit': 0.00 if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else -gross_value,
                    'credit': gross_value if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': accounts.asset_clearing_analytic_account_id.id if accounts.asset_clearing_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                for tag in accounts.asset_cost_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                # debit
                move_line_2 = {
                    'name': trx_name,
                    'account_id': asset_cost_account,
                    'credit': 0.00 if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else -gross_value,
                    'debit': gross_value if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': accounts.asset_cost_analytic_account_id.id if accounts.asset_cost_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }

                move_vals = {
                    'ref': line.asset_id.name,
                    'date': datetime.today() or False,
                    'journal_id': journal_id.id,
                    'line_ids': [(0, 0, move_line_1), (0, 0, move_line_2)],
                }
                move = line.env['account.move'].create(move_vals)
                line.write({'move_id': move.id, 'move_check': True})
                created_moves |= move

            elif line.trx_type == 're_class':
                old_accounts = line.env['asset_management.category_books'].search(
                    [('category_id', '=', line.old_category.id), ('book_id', '=', line.book_id.id)])
                new_accounts = line.env['asset_management.category_books'].search(
                    [('category_id', '=', line.category_id.id), ('book_id', '=', line.book_id.id)])
                old_asset_cost_account = old_accounts.asset_cost_account.id
                new_asset_cost_account = new_accounts.asset_cost_account.id
                old_accumulated_depreciation_account = old_accounts.accumulated_depreciation_account.id
                new_accumulated_depreciation_account = new_accounts.accumulated_depreciation_account.id
                journal_id = new_accounts.journal_id
                # date=datetime.strptime(line.trx_date[:7]+'-01',DF).date()
                acc_value = line.env['asset_management.book_assets'].search(
                    [('asset_id', '=', line.asset_id.id), ('book_id', '=', line.book_id.id)]).accumulated_value
                # dep_value=0
                # for value in depreciated_value:
                #     dep_value +=value.depreciated_value

                # credit
                for tag in old_accounts.asset_cost_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_1 = {
                    'name': trx_name,
                    'account_id': old_asset_cost_account,
                    'debit': 0.00 if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else -gross_value,
                    'credit': gross_value if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': old_accounts.asset_cost_analytic_account_id.id if old_accounts.asset_cost_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                # debit
                for tag in new_accounts.asset_cost_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_2 = {
                    'name': trx_name,
                    'account_id': new_asset_cost_account,
                    'credit': 0.00 if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else -gross_value,
                    'debit': gross_value if float_compare(gross_value, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': new_accounts.asset_cost_analytic_account_id.id if new_accounts.asset_cost_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }

                # credit
                for tag in new_accounts.accumulated_depreciation_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_3 = {
                    'name': trx_name,
                    'account_id': new_accumulated_depreciation_account,
                    'debit': 0.00 if float_compare(acc_value, 0.0, precision_digits=prec) > 0 else -acc_value,
                    'credit': acc_value if float_compare(acc_value, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': new_accounts.accumulated_depreciation_analytic_account_id.id if new_accounts.accumulated_depreciation_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                # debit
                for tag in old_accounts.accumulated_depreciation_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_4 = {
                    'name': trx_name,
                    'account_id': old_accumulated_depreciation_account,
                    'credit': 0.00 if float_compare(acc_value, 0.0, precision_digits=prec) > 0 else -acc_value,
                    'debit': acc_value if float_compare(acc_value, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': old_accounts.accumulated_depreciation_analytic_account_id.id if old_accounts.accumulated_depreciation_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }

                move_vals = {
                    'ref': self.asset_id.name,
                    'date': line.book_id.calendar_line_id.end_date or False,
                    'journal_id': journal_id.id,
                    'line_ids': [(0, 0, move_line_1), (0, 0, move_line_2), (0, 0, move_line_3), (0, 0, move_line_4)],
                }
                move = line.env['account.move'].create(move_vals)
                line.write({'move_id': move.id, 'move_check': True})
                created_moves |= move

            elif line.trx_type == 'cost_adjustment':
                cost = line.cost - line.old_cost
                accounts = line.env['asset_management.category_books'].search(
                    [('book_id', '=', line.book_id.id), ('category_id', '=', line.category_id.id)])
                journal_id = accounts.journal_id
                asset_cost_account = accounts.asset_cost_account.id
                asset_clearing_account = accounts.asset_clearing_account.id
                # credit
                for tag in accounts.asset_clearing_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_1 = {
                    'name': trx_name,
                    'account_id': asset_clearing_account,
                    'debit': 0.00 if float_compare(cost, 0.0, precision_digits=prec) > 0 else -cost,
                    'credit': cost if float_compare(cost, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': accounts.asset_clearing_analytic_account_id.id if accounts.asset_clearing_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                # debit
                for tag in accounts.asset_cost_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_2 = {
                    'name': trx_name,
                    'account_id': asset_cost_account,
                    'credit': 0.00 if float_compare(cost, 0.0, precision_digits=prec) > 0 else -cost,
                    'debit': cost if float_compare(cost, 0.0, precision_digits=prec) > 0 else 0.0,
                    'journal_id': journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * 50 or 0.0,
                    'analytic_account_id': accounts.asset_cost_analytic_account_id.id if accounts.asset_cost_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }

                move_vals = {
                    'ref': line.asset_id.name,
                    'date': datetime.today() or False,
                    'journal_id': journal_id.id,
                    'line_ids': [(0, 0, move_line_1), (0, 0, move_line_2)],
                }
                move = line.env['account.move'].create(move_vals)
                line.write({'move_id': move.id, 'move_check': True})
                created_moves |= move

        return [x.id for x in created_moves]

    @api.multi
    def generate_retirement_journal(self):
        created_moves = self.env['account.move']
        prec = self.env['decimal.precision'].precision_get('Account')
        asset_name = self.asset_id.name
        category_books = self.env['asset_management.category_books'].search([('book_id', '=', self.book_id.id), (
            'category_id', '=', self.category_id.id)])
        tag_ids = []
        for trx in self:
            current_currency = trx.asset_id.currency_id
            company_currency = trx.book_id.company_id.currency_id
            # date = datetime.strptime(trx.trx_date[:7] + '-01', DF).date()
            retirement = trx.retirement_id
            accum_value = retirement.accumulated_value
            # depreciated_value = trx.env['asset_management.depreciation'].search(
            #     [('asset_id', '=', trx.asset_id.id), ('book_id', '=', trx.book_id.id),
            #      ('depreciation_date', '<=', date),('move_posted_check','=',True)])
            # accum_value = 0
            # for value in depreciated_value:
            #     accum_value += value.depreciated_value
            cr = 0
            db = 0
            if retirement.proceeds_of_sale or retirement.cost_of_removal:
                asset_cost_account = category_books.asset_cost_account.id
                accumulated_depreciation_account = category_books.accumulated_depreciation_account.id
                for tag in category_books.asset_cost_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_1 = {
                    'name': asset_name,
                    'account_id': asset_cost_account,
                    'debit': 0.0,
                    'credit': retirement.current_asset_cost,
                    'journal_id': category_books.journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * retirement.current_asset_cost or 0.0,
                    'analytic_account_id': category_books.asset_cost_analytic_account_id.id if category_books.asset_cost_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                move_vals = {
                    'ref': trx.asset_id.name,
                    'date': trx.trx_date or False,
                    'journal_id': category_books.journal_id.id,
                    'line_ids': [(0, 0, move_line_1)],
                }
                if accum_value:
                    for tag in category_books.accumulated_depreciation_analytic_tag_ids:
                        tag_ids.append((4, tag.id, 0))
                    move_line_2 = {
                        'name': asset_name,
                        'account_id': accumulated_depreciation_account,
                        'credit': 0.0,
                        'debit': accum_value,
                        'journal_id': category_books.journal_id.id,
                        'currency_id': company_currency != current_currency and current_currency.id or False,
                        'amount_currency': company_currency != current_currency and - 1.0 * accum_value or 0.0,
                        'analytic_account_id': category_books.accumulated_depreciation_analytic_account_id.id if category_books.accumulated_depreciation_analytic_account_id else False,
                        'analytic_tag_id': tag_ids
                    }
                    move_vals['line_ids'].append([0, 0, move_line_2])
                    cr += move_line_2['credit']
                    db += move_line_2['debit']
                cr += move_line_1['credit']
                db += move_line_1['debit']

                if retirement.proceeds_of_sale:
                    for tag in retirement.retirement_type_id.proceeds_of_sale_analytic_tag_ids:
                        tag_ids.append((4, tag.id, 0))
                    proceeds_of_sale_account = retirement.retirement_type_id.proceeds_of_sale_account.id
                    move_line_3 = {
                        'name': asset_name,
                        'account_id': proceeds_of_sale_account,
                        'credit': 0.0,
                        'debit': retirement.proceeds_of_sale,
                        'journal_id': category_books.journal_id.id,
                        'currency_id': company_currency != current_currency and current_currency.id or False,
                        'amount_currency': company_currency != current_currency and - 1.0 * retirement.proceeds_of_sale or 0.0,
                        'analytic_account_id': retirement.retirement_type_id.proceeds_of_sale_analytic_account_id.id if retirement.retirement_type_id.proceeds_of_sale_analytic_account_id else False,
                        'analytic_tag_id': tag_ids
                    }
                    move_vals['line_ids'].append((0, 0, move_line_3))
                    cr += move_line_3['credit']
                    db += move_line_3['debit']

                if retirement.cost_of_removal:
                    cost_of_removal_account = retirement.retirement_type_id.cost_of_removal_account.id
                    for tag in retirement.retirement_type_id.cost_of_removal_analytic_tag_ids:
                        tag_ids.append((4, tag.id, 0))
                    move_line_4 = {
                        'name': asset_name,
                        'account_id': cost_of_removal_account,
                        'debit': 0.0,
                        'credit': retirement.cost_of_removal,
                        'journal_id': category_books.journal_id.id,
                        'currency_id': company_currency != current_currency and current_currency.id or False,
                        'amount_currency': company_currency != current_currency and - 1.0 * retirement.cost_of_removal or 0.0,
                        'analytic_account_id': retirement.retirement_type_id.cost_of_removal_analytic_account_id.id if retirement.retirement_type_id.cost_of_removal_analytic_account_id else False,
                        'analytic_tag_id': tag_ids
                    }
                    move_vals['line_ids'].append((0, 0, move_line_4))
                    cr += move_line_4['credit']
                    db += move_line_4['debit']

                if db > cr:
                    cost_of_removal_gain_account = retirement.book_id.cost_of_removal_gain_account.id
                    for tag in retirement.book_id.gain_analytic_tag_ids:
                        tag_ids.append((4, tag.id, 0))
                    move_line_5 = {
                        'name': asset_name,
                        'account_id': cost_of_removal_gain_account,
                        'debit': 0.0,
                        'credit': db - cr,
                        'journal_id': category_books.journal_id.id,
                        'currency_id': company_currency != current_currency and current_currency.id or False,
                        'amount_currency': company_currency != current_currency and - 1.0 * db - cr or 0.0,
                        'analytic_account_id': retirement.book_id.gain_analytic_account_id.id if retirement.book_id.gain_analytic_account_id else False,
                        'analytic_tag_id': tag_ids
                    }
                    move_vals['line_ids'].append((0, 0, move_line_5))
                elif db < cr:
                    cost_of_removal_loss_account = retirement.book_id.cost_of_removal_loss_account.id
                    for tag in retirement.book_id.loss_analytic_tag_ids:
                        tag_ids.append((4, tag.id, 0))
                    move_line_5 = {
                        'name': asset_name,
                        'account_id': cost_of_removal_loss_account,
                        'credit': 0.0,
                        'debit': cr - db,
                        'journal_id': category_books.journal_id.id,
                        'currency_id': company_currency != current_currency and current_currency.id or False,
                        'amount_currency': company_currency != current_currency and - 1.0 * db - cr or 0.0,
                        'analytic_account_id': retirement.book_id.loss_analytic_account_id.id if retirement.book_id.loss_analytic_account_id else False,
                        'analytic_tag_id': tag_ids
                    }
                    move_vals['line_ids'].append((0, 0, move_line_5))
                # move1 = trx.env['account.move'].create(move_vals1)
            elif self.trx_type == 'partial_retirement' and retirement.retired_cost <= accum_value:
                for tag in category_books.asset_cost_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                asset_cost_account = category_books.asset_cost_account.id
                accumulated_depreciation_account = category_books.accumulated_depreciation_account.id
                # credit
                move_line_1 = {
                    'name': asset_name,
                    'account_id': asset_cost_account,
                    'debit': 0.0 if float_compare(retirement.retired_cost, 0.0,
                                                  precision_digits=prec) > 0 else -retirement.retired_cost,
                    'credit': retirement.retired_cost if float_compare(retirement.retired_cost, 0.0,
                                                                       precision_digits=prec) > 0 else 0.0,
                    'journal_id': category_books.journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * retirement.retired_cost or 0.0,
                    'analytic_account_id': category_books.asset_cost_analytic_account_id.id if category_books.asset_cost_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }

                # debit
                for tag in category_books.accumulated_depreciation_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_2 = {
                    'name': asset_name,
                    'account_id': accumulated_depreciation_account,
                    'credit': 0.0 if float_compare(retirement.retired_cost, 0.0,
                                                   precision_digits=prec) > 0 else -retirement.retired_cost,
                    'debit': retirement.retired_cost if float_compare(retirement.retired_cost, 0.0,
                                                                      precision_digits=prec) > 0 else 0.0,
                    'journal_id': category_books.journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * retirement.retired_cost or 0.0,
                    'analytic_account_id': category_books.accumulated_depreciation_analytic_account_id.id if category_books.accumulated_depreciation_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                move_vals = {
                    'ref': trx.asset_id.name,
                    'date': trx.trx_date or False,
                    'journal_id': category_books.journal_id.id,
                    'line_ids': [(0, 0, move_line_1), (0, 0, move_line_2)],
                }
            else:
                for tag in category_books.asset_cost_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                asset_cost_account = category_books.asset_cost_account.id
                accumulated_depreciation_account = category_books.accumulated_depreciation_account.id
                cost_of_removal_loss_account = trx.book_id.cost_of_removal_loss_account.id
                # credit
                move_line_1 = {
                    'name': asset_name,
                    'account_id': asset_cost_account,
                    'debit': 0.0 if float_compare(retirement.retired_cost, 0.0,
                                                  precision_digits=prec) > 0 else -retirement.retired_cost,
                    'credit': retirement.retired_cost if float_compare(retirement.retired_cost, 0.0,
                                                                       precision_digits=prec) > 0 else 0.0,
                    'journal_id': category_books.journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * retirement.retired_cost or 0.0,
                    'analytic_account_id': category_books.asset_cost_analytic_account_id.id if category_books.asset_cost_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }
                # debit
                debit_amount = retirement.retired_cost - accum_value
                for tag in trx.book_id.loss_analytic_tag_ids:
                    tag_ids.append((4, tag.id, 0))
                move_line_3 = {
                    'name': asset_name,
                    'account_id': cost_of_removal_loss_account,
                    'credit': 0.0 if float_compare(debit_amount, 0.0,
                                                   precision_digits=prec) > 0 else -debit_amount,
                    'debit': debit_amount if float_compare(debit_amount, 0.0,
                                                           precision_digits=prec) > 0 else 0.0,
                    'journal_id': category_books.journal_id.id,
                    'currency_id': company_currency != current_currency and current_currency.id or False,
                    'amount_currency': company_currency != current_currency and - 1.0 * debit_amount or 0.0,
                    'analytic_account_id': trx.book_id.loss_analytic_account_id.id if trx.book_id.loss_analytic_account_id else False,
                    'analytic_tag_id': tag_ids
                }

                move_vals = {
                    'ref': trx.asset_id.name,
                    'date': trx.trx_date or False,
                    'journal_id': category_books.journal_id.id,
                    'line_ids': [(0, 0, move_line_1), (0, 0, move_line_3)],
                }
                # debit
                if accum_value:
                    for tag in category_books.accumulated_depreciation_analytic_tag_ids:
                        tag_ids.append((4, tag.id, 0))
                    move_line_2 = {
                        'name': asset_name,
                        'account_id': accumulated_depreciation_account,
                        'credit': 0.0 if float_compare(accum_value, 0.0,
                                                       precision_digits=prec) > 0 else -accum_value,
                        'debit': accum_value if float_compare(accum_value, 0.0,
                                                              precision_digits=prec) > 0 else 0.0,
                        'journal_id': category_books.journal_id.id,
                        'currency_id': company_currency != current_currency and current_currency.id or False,
                        'amount_currency': company_currency != current_currency and - 1.0 * accum_value or 0.0,
                        'analytic_account_id': category_books.accumulated_depreciation_analytic_account_id.id if category_books.accumulated_depreciation_analytic_account_id else False,
                        'analytic_tag_id': tag_ids
                    }
                    move_vals['line_ids'].append((0, 0, move_line_2))
            move = trx.env['account.move'].create(move_vals)
            trx.write({'move_id': move.id, 'move_check': True})
            retirement.write({'state': 'complete'})
            created_moves |= move
        return [x.id for x in created_moves]

    @api.multi
    def unlink(self):
        for record in self:
            raise ValidationError(_('Transaction can not be deleted '))
        super(Transaction, self).unlink()


class AssetTag(models.Model):
    _name = 'asset_management.tag'
    name = fields.Char()


class AssetLocation(models.Model):
    _name = 'asset_management.location'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(required=True, track_visibility='always')
    city = fields.Char(required=True, track_visibility='always')
    state_id = fields.Many2one('res.country.state', track_visibility='always')
    country_id = fields.Many2one('res.country', required=True, track_visibility='always')
    active = fields.Boolean(default=True, track_visibility='onchange')


class RetirementType(models.Model):
    _name = 'asset_management.retirement_type'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(required=True, track_visibility='always')
    proceeds_of_sale_account = fields.Many2one('account.account', on_delete='set_null', required=True,
                                               track_visibility='onchange')
    cost_of_removal_account = fields.Many2one('account.account', on_delete='set_null', required=True,
                                              track_visibility='onchange')
    proceeds_of_sale_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                                           track_visibility='onchange')
    proceeds_of_sale_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                                         track_visibility='onchange')
    cost_of_removal_analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account',
                                                          track_visibility='onchange')
    cost_of_removal_analytic_tag_ids = fields.Many2many('account.analytic.tag', string='Analytic tags',
                                                        track_visibility='onchange')
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env['res.company']._company_default_get(
                                     'asset_management.book'))

    @api.onchange('name', 'company_id')
    def _accounts_domain(self):
        for record in self:
            return {'domain': {'proceeds_of_sale_account': [('company_id', '=', record.company_id.id)],
                               'cost_of_removal_account': [('company_id', '=', record.company_id.id)],
                               'proceeds_of_sale_analytic_account_id': [('company_id', '=', record.company_id.id)],
                               'cost_of_removal_analytic_account_id': [('company_id', '=', record.company_id.id)]
                               }}


class Calendar(models.Model):
    _name = 'asset_management.calendar'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(required=True, track_visibility='always')
    calendar_lines_id = fields.One2many('asset_management.calendar_line', 'calendar_id', on_delete='cascade')
    calender_one2many_view = fields.Boolean(default=True, readonly=True)

    @api.model
    def create(self, values):
        if 'calendar_lines_id' not in values:
            raise UserError(_('period must be added'))
        record = super(Calendar, self).create(values)
        record._check_periods()
        return record

    @api.multi
    def write(self, values):
        super(Calendar, self).write(values)
        if 'calendar_lines_id' not in values:
            raise UserError(_('period must be added'))
        self._check_periods()

    def _check_periods(self):
        period = self.calendar_lines_id.sorted(key=lambda l: l.end_date)
        for a, b in zip(period, period[1:]):
            a_end_date = a.end_date + relativedelta(days=+1)
            if a.end_date > b.start_date:
                raise ValidationError(_('periods ' + a.name + ' and ' + b.name + ' are not '))
            elif a_end_date != b.start_date:
                raise ValidationError(_('periods ' + a.name + ' and ' + b.name + ' are not d'))


class CalendarLines(models.Model):
    _name = 'asset_management.calendar_line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char('Period Name', required=True, track_visibility='always')
    start_date = fields.Date(required=True, track_visibility='onchange')
    end_date = fields.Date(required=True, track_visibility='onchange')
    calendar_id = fields.Many2one('asset_management.calendar', on_delete="cascade", track_visibility='onchange')

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(CalendarLines, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('calender_one2many_view'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.end_date < record.start_date:
                raise ValidationError(_("Closing Date cannot be set before Beginning Date in " + record.name))

        # if self.company_id.fiscalyear_lock_date:
        #     if self.company_id.fiscalyear_lock_date > self.start_date:
        #         raise ValidationError(_("Start date must be after fiscal year lock date,"
        #                                 "\n change the start date or the fiscal year date in accounting "))


class DepRunProcess(models.Model):
    _name = "asset_management.deprunprocess"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char('Run Deprecation process Number', track_visibility='always')
    process_date = fields.Date()
    process_period_id = fields.Many2one('asset_management.calendar_line', on_delete="cascade",
                                        track_visibility='onchange')
    book_id = fields.Many2one('asset_management.book', on_delete="cascade", track_visibility='onchange')
    dep_run_process_lines = fields.One2many('asset_management.deprunprocess_line', 'dep_run_process_id')
    reinstall_flag = fields.Boolean()
    dep_on2many_view = fields.Boolean(default=True)

    @api.model
    def create(self, vals):
        vals['name'] = self.env['ir.sequence'].next_by_code('asset_management.deprunprocess.DepRunProcess')
        record = super(DepRunProcess, self).create(vals)
        return record

    @api.multi
    def reinstall(self):
        dep_line = self.env['asset_management.depreciation'].search([('dep_run_process_id', '=', self.id)])
        date = datetime.today()
        reserved_jl_list = []
        for line in dep_line:
            journal_entries = line.move_id
            journal_id = journal_entries.journal_id
            reserved_jl = self.env['account.move'].browse(journal_entries.id).reverse_moves(date, journal_id)
            # reserved_jl = journal_entries.reverse_moves(date, journal_id)
            for x in reserved_jl:
                reserved_jl_list.append(x)
            line.write({'dep_run_process_id': False,
                        'move_id': False,
                        'move_check': False,
                        'period_id': False,
                        'move_posted_check': False})
        if reserved_jl_list:
            self.reinstall_flag = True
            return {
                'name': _('Reinstall move'),
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'tree,form',
                'res_model': 'account.move',
                'domain': [('id', 'in', reserved_jl_list)],
            }

    @api.multi
    def unlink(self):
        for record in self:
            raise ValidationError(_('Depreciation Run Process can not be deleted '))
        super(DepRunProcess, self).unlink()


class DepRunProcessLine(models.Model):
    _name = 'asset_management.deprunprocess_line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    name = fields.Char(track_visibility='always')
    sequence = fields.Integer(track_visibility='onchange')
    dep_run_process_id = fields.Many2one('asset_management.deprunprocess', on_delete='cascade',
                                         track_visibility='onchange')
    depreciation_id = fields.Many2one('asset_management.depreciation', on_delete='cascade', track_visibility='onchange')

    @api.multi
    def unlink(self):
        for record in self:
            raise ValidationError(_('Depreciation Run Process history can not be deleted '))
        super(DepRunProcessLine, self).unlink()

    @api.model
    def fields_view_get(self, view_id=False, view_type='form', toolbar=False, submenu=False):
        res = super(DepRunProcessLine, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('dep_on2many_view'):
            doc = etree.XML(res['arch'])
            for node in doc.xpath("//field[@name='message_follower_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='activity_ids']"):
                node.set('widget', "")
            for node in doc.xpath("//field[@name='message_ids']"):
                node.set('widget', "")
            res['arch'] = etree.tostring(doc, encoding='unicode')
        return res
