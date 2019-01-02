
from odoo import api, models, _
from datetime import date, datetime


class StudentAttendanceReport(models.AbstractModel):
    _name = 'report.report.manufacturing_orders_template'


    @api.model
    def man_order(self, docids, data=None):
        # docs = []
        record_id = data['ids']
        mrp_order = self.env['mrp.production'].browse([('date_planned_start','&gt;=', datetime.combine(context_today(), datetime.time(0,0,0))),
                                                       ('date_planned_start','&lt;=',datetime.combine(context_today(), datetime.time(23,59,59)))])

        # for order in mrp_order:
        #     res = dict((fn, 0.0) for fn in ['order_name', 'state', 'product_name','responsible'])
        #     res['order_name'] = order.name
        #     res['state'] =order.state
        #     res['product_name'] = order.product_id.name
        #     res['responsible'] = order.user_id
        #     docs.append(res)
        docs = mrp_order


        return {
            'doc_ids': docs.ids,
            'doc_model':'mrp.production',
            'docs': docs,
        }


