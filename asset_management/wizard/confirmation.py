# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, datetime

class Confirmation(models.TransientModel):
    _name='asset_management.confirmation_wizard'
    # date = fields.Date()
    slist = fields.Char()
    text = fields.Char()


    @api.multi
    def confirm(self):
        source_id= self.env.context.get('active_id')
        self.env['asset_management.source_line'].search([('id','=',source_id)]).unlink()
        # for s in self.slist:
        # d.append((6, False, self.slist))
        # book_asset_id.write({'source_line_ids':[(6, False, self.slist)]})
        # book_asset_id.date_in_service = self.date
        return {'type': 'ir.actions.act_window_close'}

    # def cancel(self):
    #     book_asset_id = self.env.context.get('active_id')
    #     book_asset_id.date_in_service = False
    #     return {'type': 'ir.actions.act_window_close'}

