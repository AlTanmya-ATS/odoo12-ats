# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.tools.safe_eval import safe_eval


MASS_re_class_MODELS = [
    'asset_management.book_assets',
]


class ReClass(models.TransientModel):
    _name='asset_management.re_class_wizard'
    # asset_id=fields.Many2one('asset_management.asset')
    # book_id=fields.Many2one('asset_management.book',domain=[('active','=',True)])
    # category_id=fields.Many2one('asset_management.category',compute="_get_book_category")
    new_category_id=fields.Many2one('asset_management.category',domain=[('active','=',True)])

    # mailing_model_real = fields.Char(compute='_compute_model', string='Recipients Real Model', default='mail.mass_mailing.contact', required=True)
    model_id = fields.Many2one('ir.model', string='Recipients Model', domain=[('model', '=', MASS_re_class_MODELS)],
                               default=lambda self: self.env.ref('asset_management.model_asset_management_book_assets').id)
    model_name = fields.Char(related='model_id.model', string='Recipients Model Name')
    reclass_domain = fields.Char(string='Domain', oldname='domain', default=[])


    # @api.depends('mailing_model_id')
    # def _compute_model(self):
    #     for record in self:
    #         record.mailing_model_real = (record.mailing_model_name != 'mail.mass_mailing.list') and record.mailing_model_name or 'mail.mass_mailing.contact'

    # @api.onchange('book_id')
    # def _asset_in_book_domain(self):
    #     if self.book_id:
    #         res=[]
    #         assets_in_book=self.env['asset_management.book_assets'].search([('book_id','=',self.book_id.id),('state','=','open')])
    #         for asset in assets_in_book:
    #             res.append(asset.asset_id.id)
    #
    #         return {'domain':{'asset_id':[('id','in',res)]
    #                           }}
    #
    #
    # @api.onchange('asset_id')
    # def _onchange_asset_id(self):
    #     if self.asset_id:
    #         categorys = []
    #         category_books = self.env['asset_management.category_books'].search([('book_id', '=', self.book_id.id)])
    #         for record in category_books:
    #             if record.category_id.active and record.category_id.id != self.category_id.id:
    #                 categorys.append(record.category_id.id)
    #
    #         return {'domain': {'new_category_id': [('id', 'in', categorys)]
    #                            }}
    #
    # @api.depends('book_id','asset_id')
    # def _get_book_category(self):
    #     category_of_book=self.env['asset_management.book_assets'].search([('book_id','=',self.book_id.id),('asset_id','=',self.asset_id.id)])
    #     self.category_id=category_of_book.category_id.id

    def _get_domain(self):
        if self.reclass_domain:
            domain = safe_eval(self.reclass_domain)
            res = self.env['asset_management.book_assets'].search(domain).ids
            return res


    @api.multi
    def asset_re_class(self):
        records_ids = self._get_domain()
        for record in records_ids:
            new_category = self.env['asset_management.book_assets'].search([('id','=',record)])


            # new_category=self.env['asset_management.book_assets'].search([('asset_id','=',records.asset_id.id),('book_id','=',records.book_id.id)])
            new_depreciation_expense_account=self.env['asset_management.category_books'].search([('category_id','=',self.new_category_id.id),
                                                                                                 ('book_id','=',new_category.book_id.id)]).depreciation_expense_account

            new_values={
            'category_id':self.new_category_id.id
            }
            new_category.write(new_values)
            for assignment in new_category.assignment_id:
                assignment.depreciation_expense_account = new_depreciation_expense_account.id
        return {'type':'ir.actions.act_window_close'}
