from odoo import api, fields, models,_
from lxml import etree
from odoo.osv.orm import setup_modifiers


class AssetModify(models.TransientModel):
    _name = 'asset_management.modify'
    _description = 'Modify asset depreciation'

    name = fields.Char(readonly=True)
    method_number=fields.Integer(string='Number Of Depreciation')
    life_months=fields.Integer()
    end_date=fields.Date()
    asset_method_time=fields.Char(compute='_get_asset_method_time', string='Asset Method Time', readonly=True)


    @api.one
    def _get_asset_method_time(self):
        if self.env.context.get('active_id'):
            book_asset=self.env['asset_management.book_assets'].browse(self.env.context.get('active_id')).method_time
            self.asset_method_time=book_asset


    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        result = super(AssetModify, self).fields_view_get(view_id, view_type, toolbar=toolbar, submenu=submenu)
        asset_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')
        if active_model == 'asset_management.book_assets' and asset_id:
            asset = self.env['asset_management.book_assets'].browse(asset_id)
            doc = etree.XML(result['arch'])
            if asset.method_time == 'number' and doc.xpath("//field[@name='end_date']"):
                node = doc.xpath("//field[@name='end_date']")[0]
                node.set('invisible', '1')
                setup_modifiers(node, result['fields']['end_date'])
            elif asset.method_time == 'end' and doc.xpath("//field[@name='method_number']"):
                node = doc.xpath("//field[@name='method_number']")[0]
                node.set('invisible', '1')
                setup_modifiers(node, result['fields']['method_number'])
            result['arch'] = etree.tostring(doc, encoding='unicode')
        return result


    @api.model
    def default_get(self, fields):
        res = super(AssetModify, self).default_get(fields)
        asset_id = self.env.context.get('active_id')
        asset = self.env['asset_management.book_assets'].browse(asset_id)
        if 'name' in fields:
            res.update({'name': asset.name})
        if 'method_number' in fields and asset.method_time == 'number':
            res.update({'method_number': asset.method_number})
        if 'life_months' in fields:
            res.update({'life_months': asset.life_months})
        if 'end_date' in fields and asset.method_time == 'end':
            res.update({'end_date': asset.end_date})
        if self.env.context.get('active_id'):
            active_asset = self.env['asset_management.book_assets'].browse(self.env.context.get('active_id'))
            res['asset_method_time'] = active_asset.method_time
        return res

    @api.multi
    def modify(self):
        book_asset_id=self.env.context.get('active_id')
        book_asset=self.env['asset_management.book_assets'].search([('id','=',book_asset_id)])
        new_values={
            'method_number':self.method_number,
            'life_months':self.life_months,
            'end_date':self.end_date
        }

        book_asset.write(new_values)
        book_asset.compute_depreciation_board()
        return {'type':'ir.actions.act_window_close'}


