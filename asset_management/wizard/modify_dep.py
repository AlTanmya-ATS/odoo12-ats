from odoo import fields,api,models,_
from odoo.tools.safe_eval import safe_eval

MASS_modify_models_MODELS = [
    'asset_management.book_assets',
]

class ModifyDep(models.TransientModel):
    _name='asset_management.modify_dep'
    name = fields.Char()
    # asset_id=fields.Many2one('asset_management.asset')
    # book_id=fields.Many2one('asset_management.book',domain=[('active','=',True)])
    model_id = fields.Many2one('ir.model', string='Recipients Model', domain=[('model', '=', MASS_modify_models_MODELS)],
                               default=lambda self: self.env.ref('asset_management.model_asset_management_book_assets').id)
    model_name = fields.Char(related='model_id.model', string='Recipients Model Name')
    modify_dep_domain = fields.Char(string='Domain', oldname='domain', default=[])

    dep_method=fields.Selection([('linear','Linear'),('degressive','Degressive')],string='Deprecation Method',default='linear')
    life_months=fields.Integer()
    method_number=fields.Integer()
    method_progress_factor=fields.Float()
    method_time=fields.Selection([('end','End Date'),('number','Number of entries')],default='number')
    end_date=fields.Date()

    # @api.onchange('book_id')
    # def _asset_in_book_domain(self):
    #     if self.book_id:
    #         res=[]
    #         assets_in_book=self.env['asset_management.book_assets'].search([('book_id','=',self.book_id.id),('depreciated_flag','=',True)])
    #         for asset in assets_in_book:
    #             res.append(asset.asset_id.id)
    #
    #         return {'domain':{'asset_id':[('id','in',res)]
    #                           }}

    # @api.onchange('book_id','asset_id')
    # def get_record_values(self):
    #     vals = self.onchange_book_assets_id_value(self.book_id.id,self.asset_id.id)
    #     # We cannot use 'write' on an object that doesn't exist yet
    #     if vals:
    #         for k, v in vals['value'].items():
    #             setattr(self, k, v)
    #
    # def onchange_book_assets_id_value(self, book_id,asset_id):
    #     if book_id and asset_id:
    #         asset = self.env['asset_management.book_assets'].search(
    #             [('book_id', '=', self.book_id.id), ('asset_id', '=', self.asset_id.id)])
    #         return {
    #             'value': {
    #                 'dep_method': asset.method,
    #                 'life_months': asset.life_months,
    #                 'method_progress_factor': asset.method_progress_factor,
    #                 'method_time': asset.method_time,
    #                 'method_number': asset.method_number,
    #                 'end_date': asset.end_date,
    #             }
    #         }

    def _get_domain(self):
        if self.modify_dep_domain:
            domain = safe_eval(self.modify_dep_domain)
            res = self.env['asset_management.book_assets'].search(domain).ids
            return res

    @api.multi
    def modify(self):
        records_ids = self._get_domain()
        for record in records_ids:
            asset = self.env['asset_management.book_assets'].search([('id', '=', record)])
            # asset = self.env['asset_management.book_assets'].search([('asset_id','=',record.asset_id.id),('book_id','=',record.book_id.id)])
            new_values={
                'method':self.dep_method,
                'life_months':self.life_months,
                'method_progress_factor':self.method_progress_factor,
                'method_time':self.method_time,
                'method_number':self.method_number,
                'end_date':self.end_date
            }
            asset.write(new_values)
            asset.compute_depreciation_board()
        return {'type':'ir.actions.act_window_close'}
