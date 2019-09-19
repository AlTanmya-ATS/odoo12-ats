# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, datetime


class Confirmation(models.TransientModel):
    _name = 'asset_management.confirmation_wizard'
    # date = fields.Date()

    text = fields.Char()

    @api.multi
    def confirm(self):
        val = self.env.context.get('values')
        values = {
            'book_assets_id': self.env.context.get('active_id'),
            'source_type': val['source_type'] if val['source_type'] else False,
            'amount_m_type': val['amount_m_type'] if val['amount_m_type'] else False,
            'invoice_id': val['invoice_id'] if val['invoice_id'] else False,
            'invoice_line_ids': val['invoice_line_ids'] if val['invoice_line_ids'] else False,
            'amount': val['amount'] if val['amount'] else False,
            'invoice_id_m_type': val['invoice_id_m_type'] if val['invoice_id_m_type'] else False,
            'invoice_line_ids_m_type': val['invoice_line_ids_m_type'] if val['invoice_line_ids_m_type'] else False,
            'description': val['description'] if val['description'] else False,
            'added_to_asset_cost': True
        }

        asset = self.env['asset_management.book_assets'].search([('id', '=', self.env.context.get('active_id'))])
        asset.write({'source_line_ids': [(0, 0, values)],
                     'current_cost': asset.current_cost + val['amount_m_type'] or asset.current_cost + val['amount']
                     })

        return {'type': 'ir.actions.act_window_close'}
