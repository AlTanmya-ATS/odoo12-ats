from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, datetime


class AddSoyrceLine(models.TransientModel):
    _name = 'asset_management.add_source_line'
    source_type = fields.Selection(
        [('invoice', 'Invoice'), ('miscellaneous', 'Miscellaneous')
         ], default='invoice', required=True,
    )
    invoice_id = fields.Many2one("account.invoice", string="invoice", ondelete='cascade', )
    invoice_line_ids = fields.Many2one("account.invoice.line", string="Invoice Line", ondelete='cascade',
                                       )
    amount = fields.Float('Amount', compute="_get_price_from_invoice", track_visibility='onchange')
    invoice_id_m_type = fields.Char('Invoice')
    invoice_line_ids_m_type = fields.Char('Invoice Line', track_visibility='onchange')
    amount_m_type = fields.Float('Amount')
    description = fields.Text()

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

    @api.multi
    def add(self):
        book_asset_id = self.env['asset_management.book_assets'].browse(self.env.context.get('active_id'))
        net_book_value = book_asset_id.net_book_value
        values = {
            'source_type': self.source_type,
            'invoice_id': self.invoice_id.id if self.invoice_id else False,
            'invoice_line_ids': self.invoice_line_ids.id if self.invoice_line_ids else False,
            'amount': self.amount,
            'invoice_id_m_type': self.invoice_id_m_type if self.invoice_id_m_type else False,
            'invoice_line_ids_m_type': self.invoice_line_ids_m_type if self.invoice_line_ids_m_type else False,
            'amount_m_type': self.amount_m_type if self.amount_m_type else False,
            'description': self.description
        }

        #         if self.source_type == 'invoice' and self.amount == 0 or self.source_type == 'miscellaneous' and self.amount_m_type == 0:
        #             raise ValidationError (_("source amount must not be zero"))

        if self.source_type == 'invoice' and net_book_value + self.amount or self.source_type == 'miscellaneous' and net_book_value + self.amount_m_type > 0:
            text = "new net book value is " + str(
                net_book_value + self.amount_m_type + self.amount) + " \n Are you sure you want to add this source line"
            return {
                'type': 'ir.actions.act_window',
                'name': _('Warning'),
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'asset_management.confirmation_wizard',
                'target': 'new',
                'view_id': self.env.ref('asset_management.confirmation_wizard', False),
                'context': {'active_id': self.env.context.get('active_id'), 'values': values, 'default_text': text,
                            },

            }

        elif self.source_type == 'invoice' and net_book_value + self.amount == 0 or self.source_type == 'miscellaneous' and net_book_value + self.amount_m_type == 0:
            text = "new net book value is 0.0 \nAre you sure you want to add this source line"
            return {
                'type': 'ir.actions.act_window',
                'name': _('Warning'),
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'asset_management.confirmation_wizard',
                'target': 'new',
                'view_id': self.env.ref('asset_management.confirmation_wizard', False),
                'context': {'active_id': self.env.context.get('active_id'), 'values': values, 'default_text': text, }
            }

        #             book_asset_id.write({'source_line_ids':[(0,0,values)]
        #                             })
        #             return {'type': 'ir.actions.act_window_close'}

        if self.source_type == 'invoice' and net_book_value + self.amount < 0 or self.source_type == 'miscellaneous' and net_book_value + self.amount_m_type < 0:
            raise ValidationError(_("net book value is < 0.0  \nyou can't add this source line "))





