from urllib.parse import quote, urlencode

from odoo import models


def _context_hub_action(record):
    hub_url = record.env["ir.config_parameter"].sudo().get_param("context_hub.url", "").rstrip("/")
    if not hub_url:
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Context Hub",
                "message": "Configurez d’abord l’URL de Context Hub dans les paramètres généraux.",
                "type": "warning",
                "sticky": False,
            },
        }
    base_url = record.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
    source_url = f"{base_url}/web#id={record.id}&model={quote(record._name)}&view_type=form"
    query = urlencode(
        {
            "model": record._name,
            "record_id": record.id,
            "title": record.display_name,
            "source_url": source_url,
        }
    )
    return {
        "type": "ir.actions.act_url",
        "url": f"{hub_url}/integrations/odoo/open?{query}",
        "target": "new",
    }


class CrmLead(models.Model):
    _inherit = "crm.lead"

    def action_open_context_hub(self):
        self.ensure_one()
        return _context_hub_action(self)


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_open_context_hub(self):
        self.ensure_one()
        return _context_hub_action(self)


class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_open_context_hub(self):
        self.ensure_one()
        return _context_hub_action(self)


class ProjectTask(models.Model):
    _inherit = "project.task"

    def action_open_context_hub(self):
        self.ensure_one()
        return _context_hub_action(self)
