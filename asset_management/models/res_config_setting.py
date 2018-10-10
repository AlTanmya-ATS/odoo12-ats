
from odoo import models,fields,api,_

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # tracking = fields.Boolean('Tracking', help = "Enable traceability")
    group_tracking_product = fields.Boolean(implied_group="asset_management.group_tracking_product" , help ="Enable traceability")
    stock_production_lot = fields.Boolean()

    @api.onchange('group_tracking_product')
    def _onchange_tracking(self):
        if self.group_tracking_product :
            query = """ Select state from ir_module_module where name = %s """
            state = self._cr.execute (query,'stock')
            if  not state == 'installed' :
                raise Validationerror (_("Inventory model has to be installed"))
            elif state == "installed" :
                stock = self.env['res.config.setting']
                stock_lot = stock.group_stock_production_lot
                if not stock_lot :
                    raise Validationerror (_("Lots & Serial Numbers must be activate in Inventory general setting"))




