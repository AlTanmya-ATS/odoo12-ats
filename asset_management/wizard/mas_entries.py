# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, datetime
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT as DF

class MasEntriesWizard(models.TransientModel):
    _name='asset_management.mas_entries_wizard'
    # date_from=fields.Date(required=True)
    # date_to = fields.Date(required=True,)
    period_id=fields.Many2one('asset_management.calendar_line',compute="_get_current_period_id")
    post_entries=fields.Boolean()
    open_next_period = fields.Boolean()
    open_next_period_flag_enable = fields.Boolean(compute = '_open_next_period_flag_enable')
    book_id = fields.Many2one('asset_management.book', required=True,
                              domain=[('active', '=', True)])


    @api.depends('period_id')
    def _open_next_period_flag_enable(self):
        for record in self:
            if record.period_id:
                if  datetime.strptime(record.period_id.end_date,DF).date() <= datetime.today().date() :
                    record.open_next_period_flag_enable = True


    @api.multi
    def _run_dep_process(self):
        dep_run_process_id = self.env['asset_management.deprunprocess'].create({
            'process_date':datetime.today(),
            'process_period_id':self.period_id.id,
            'book_id':self.book_id.id
        })
        return dep_run_process_id


    @api.one
    @api.depends('book_id')
    def _get_current_period_id(self):
        for record in self:
            if record.book_id:
                record.period_id = record.book_id.calendar_line_id.id


    @api.multi
    def moves_compute(self):
        run_number_process = self._run_dep_process()
        asset_move_ids=self.env['asset_management.asset'].generate_mas_entries(self.period_id,self.post_entries,self.book_id.id,run_number_process.id)

        if self.post_entries is True:
            for record in asset_move_ids:
                record.move_id.post()

        if self.open_next_period:
            self.book_id.open_next_period(self.period_id.id)

        moved_lines=[]
        for record in asset_move_ids:
            moved_lines.append(record.move_id.id)



        return {
            'name':_('Created Assets Move'),
            'res_model':'account.move',
            'view_type':'form',
            'view_mode':'tree,form',
            'view_id':False,
            'type': 'ir.actions.act_window',
            'domain':[('id','in',moved_lines)],
        }