# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.tools.safe_eval import safe_eval

MASS_re_class_MODELS = [
    'asset_management.book_assets',
]


class ReClass(models.TransientModel):
    _name = 'asset_management.re_class_wizard'
    new_category_id = fields.Many2one('asset_management.category', domain=[('active', '=', True)], required=True)

    # mailing_model_real = fields.Char(compute='_compute_model', string='Recipients Real Model', default='mail.mass_mailing.contact', required=True)
    model_id = fields.Many2one('ir.model', string='Recipients Model', domain=[('model', '=', MASS_re_class_MODELS)],
                               default=lambda self: self.env.ref(
                                   'asset_management.model_asset_management_book_assets').id)
    model_name = fields.Char(related='model_id.model', string='Recipients Model Name', readonly=True)
    reclass_domain = fields.Char(string='Domain', oldname='domain', default=[])

    def _get_domain(self):
        if self.reclass_domain:
            domain = safe_eval(self.reclass_domain)
            res = self.env['asset_management.book_assets'].search(domain).ids
            return res

    @api.multi
    def asset_re_class(self):
        records_ids = self._get_domain()
        for record in records_ids:
            new_category = self.env['asset_management.book_assets'].search([('id', '=', record)])

            # new_category=self.env['asset_management.book_assets'].search([('asset_id','=',records.asset_id.id),('book_id','=',records.book_id.id)])
            new_depreciation_expense_account = self.env['asset_management.category_books'].search(
                [('category_id', '=', self.new_category_id.id),
                 ('book_id', '=', new_category.book_id.id)]).depreciation_expense_account

            new_values = {
                'category_id': self.new_category_id.id
            }
            new_category.write(new_values)
            for assignment in new_category.assignment_id:
                assignment.depreciation_expense_account = new_depreciation_expense_account.id
        return {'type': 'ir.actions.act_window_close'}
