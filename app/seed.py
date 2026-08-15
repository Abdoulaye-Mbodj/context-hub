from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Activity, Context, Resource


def seed_demo_data(db: Session) -> None:
    if db.scalar(select(func.count(Context.id))):
        return

    now = datetime.now(UTC)
    contexts = [
        Context(
            title="Renouvellement · Helios Logistics",
            summary="Centralise la négociation 2026, les validations juridiques et le plan de déploiement Europe.",
            context_type="client",
            status="active",
            priority="high",
            owner_name="Camille Martin",
            owner_email="camille@acme.fr",
            color="#5b5ce2",
            tags=["Enterprise", "Renouvellement", "EMEA"],
            due_at=now + timedelta(days=8),
        ),
        Context(
            title="Lancement produit · Atlas",
            summary="Préparation du lancement, coordination marketing et retours du programme pilote.",
            context_type="project",
            status="active",
            priority="normal",
            owner_name="Sofia Benali",
            owner_email="sofia@acme.fr",
            color="#0f9f86",
            tags=["Produit", "Go-to-market"],
            due_at=now + timedelta(days=21),
        ),
        Context(
            title="Opportunité · Maison Lenoir",
            summary="Qualification du besoin omnicanal et préparation de la démonstration métier.",
            context_type="opportunity",
            status="watching",
            priority="normal",
            owner_name="Thomas Leroy",
            owner_email="thomas@acme.fr",
            color="#f59e0b",
            tags=["Retail", "Pipeline"],
            due_at=now + timedelta(days=3),
        ),
        Context(
            title="Programme conformité RGPD",
            summary="Suivi transverse des actions juridiques, sécurité et opérations.",
            context_type="activity",
            status="active",
            priority="high",
            owner_name="Lina Dupont",
            owner_email="lina@acme.fr",
            color="#e65c6a",
            tags=["Conformité", "Interne"],
            due_at=now + timedelta(days=45),
        ),
    ]
    db.add_all(contexts)
    db.flush()

    helios = contexts[0]
    resources = [
        Resource(
            context_id=helios.id,
            source="gmail",
            external_id="demo-thread-helios-2026",
            title="RE: Renouvellement 2026 — proposition révisée",
            url="https://mail.google.com/mail/u/0/#search/Helios+renouvellement",
            resource_type="thread",
            excerpt="Le comité achats a validé le périmètre. Il reste à aligner la clause de réversibilité.",
            author_name="Claire Dubois",
            occurred_at=now - timedelta(hours=2),
            extra={"message_count": 14},
        ),
        Resource(
            context_id=helios.id,
            source="drive",
            external_id="demo-drive-helios-proposal",
            title="Proposition commerciale Helios · v6",
            url="https://drive.google.com/drive/u/0/search?q=Helios",
            resource_type="document",
            excerpt="Version de travail partagée avec Finance et Juridique.",
            author_name="Camille Martin",
            occurred_at=now - timedelta(days=1),
            extra={"mime_type": "application/vnd.google-apps.document"},
        ),
        Resource(
            context_id=helios.id,
            source="calendar",
            external_id="demo-event-helios-steerco",
            title="Comité de pilotage · Helios",
            url="https://calendar.google.com/calendar/u/0/r/search?q=Helios",
            resource_type="event",
            excerpt="Décision attendue sur le calendrier de migration.",
            author_name="Camille Martin",
            occurred_at=now + timedelta(days=2),
            extra={"attendees": 8, "duration_minutes": 45},
        ),
        Resource(
            context_id=helios.id,
            source="chat",
            external_id="demo-space-helios-war-room",
            title="Espace #helios-renouvellement",
            url="https://chat.google.com/",
            resource_type="space",
            excerpt="Thomas : la simulation de marge est disponible dans le dossier Finance.",
            author_name="Thomas Leroy",
            occurred_at=now - timedelta(hours=5),
            extra={"space_type": "SPACE"},
        ),
        Resource(
            context_id=helios.id,
            source="odoo",
            external_id="crm.lead:1842",
            title="HEL-2026 · Renouvellement EMEA",
            url="https://odoo.example.com/web#id=1842&model=crm.lead&view_type=form",
            resource_type="crm.lead",
            excerpt="Opportunité à 240 k€ · probabilité 75 %.",
            author_name="Camille Martin",
            occurred_at=now - timedelta(hours=8),
            extra={"model": "crm.lead", "record_id": 1842, "amount": 240000, "stage": "Proposition"},
        ),
    ]
    db.add_all(resources)

    # Give the remaining cards enough source variety for a useful first-run experience.
    db.add_all(
        [
            Resource(context_id=contexts[1].id, source="drive", external_id="atlas-brief", title="Brief de lancement Atlas", url="https://drive.google.com/", resource_type="document", occurred_at=now - timedelta(hours=12)),
            Resource(context_id=contexts[1].id, source="chat", external_id="atlas-space", title="#atlas-launch", url="https://chat.google.com/", resource_type="space", occurred_at=now - timedelta(hours=3)),
            Resource(context_id=contexts[1].id, source="calendar", external_id="atlas-launch-event", title="Revue Go / No-Go", url="https://calendar.google.com/", resource_type="event", occurred_at=now + timedelta(days=4)),
            Resource(context_id=contexts[2].id, source="odoo", external_id="crm.lead:2031", title="Maison Lenoir · Omnicanal", url="https://odoo.example.com/web#id=2031&model=crm.lead&view_type=form", resource_type="crm.lead", occurred_at=now - timedelta(days=2)),
            Resource(context_id=contexts[2].id, source="gmail", external_id="lenoir-discovery", title="Compte-rendu de découverte", url="https://mail.google.com/", resource_type="thread", occurred_at=now - timedelta(days=1)),
            Resource(context_id=contexts[3].id, source="drive", external_id="rgpd-register", title="Registre des traitements", url="https://drive.google.com/", resource_type="spreadsheet", occurred_at=now - timedelta(days=3)),
        ]
    )
    db.add_all(
        [
            Activity(context_id=helios.id, action="resource_added", detail="Proposition commerciale Helios · v6", actor="Camille Martin", created_at=now - timedelta(days=1)),
            Activity(context_id=helios.id, action="context_created", detail="Contexte créé depuis Odoo", actor="Camille Martin", created_at=now - timedelta(days=18)),
        ]
    )
    db.commit()
