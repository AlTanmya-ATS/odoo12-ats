from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    asset_depreciation_id = fields.One2many('asset_management.depreciation', 'move_id',
                                            string='Assets Depreciation Lines', ondelete="restrict")

    # asset_transaction_id = fields.One2many('asset_management.transaction','move_id',string='Assets Transaction Lines', ondelete="restrict")
    @api.multi
    def button_cancel(self):
        for move in self:
            for line in move.asset_depreciation_id:
                line.move_posted_check = False
        return super(AccountMove, self).button_cancel()

    @api.multi
    def post(self):
        for move in self:
            for depreciation_line in move.asset_depreciation_id:
                depreciation_line.post_lines_and_close_asset()
        return super(AccountMove, self).post()

    # @api.multi
    # def post(self):
    #     for move in self:
    #         for depreciation_line in move.asset_depreciation_id:
    #             depreciation_line.asset_id.post_lines_and_close_asset(depreciation_line.book_id.id)
    #         for transaction_line in move.asset_transaction_id:
    #             transaction_line.asset_id.post_lines_and_close_asset(transaction_line.book_id.id)
    #     return super(AccountMove, self).post()
