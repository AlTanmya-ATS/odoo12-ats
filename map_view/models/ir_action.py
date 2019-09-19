# -*- coding: utf-8 -*-

from odoo import models , fields , api

class ActWindowView(models.Model):
    _inherit="ir.actions.act_window.view"
# add view type to action to open view
    view_mode = fields.Selection(selection_add=[('map_view','Map')])


