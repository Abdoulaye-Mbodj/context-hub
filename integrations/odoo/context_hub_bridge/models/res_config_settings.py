from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    context_hub_url = fields.Char(
        string="URL de Context Hub",
        config_parameter="context_hub.url",
        help="URL publique HTTPS du service, sans barre oblique finale.",
    )
