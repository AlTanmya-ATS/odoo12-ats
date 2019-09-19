from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    asset_depreciation_id = fields.One2many('asset_management.depreciation', 'move_id',
                                            string='Assets Depreciation Lines', ondelete="restrict")
    trx_type = fields.Selection(
        [
            ('addition', 'Addition'),
            ('re_class', 'Re_Class'),
            ('transfer', 'Transfer'),
            ('cost_adjustment', 'Cost Adjustment'),
            ('full_retirement', 'Full Retirement'),
            ('partial_retirement', 'Partial Retirement'),
            ('reinstall', 'Reinstall')
        ], string='Transaction Type', track_visibility='onchange',readonly = True
    )

    # asset_transaction_id = fields.One2many('asset_management.transaction','move_id',string='Assets Transaction Lines', ondelete="restrict")
    @api.multi
    def button_cancel(self):
        for move in self:
            for line in move.asset_depreciation_id:
                line.move_posted_check = False
        return super(AccountMove, self).button_cancel()

    @api.multi
    def post(self, invoice=False):
        for move in self:
            for depreciation_line in move.asset_depreciation_id:
                depreciation_line.post_lines_and_close_asset()
        return super(AccountMove, self).post(invoice=invoice)



