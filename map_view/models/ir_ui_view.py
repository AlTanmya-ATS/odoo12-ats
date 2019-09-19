# -*- coding: utf-8 -*-

from odoo import models, fields, api

class View(models.Model):
    _inherit="ir.ui.view"
#add new type of view to server side

    type = fields.Selection(selection_add=[('map_view','Map')])
