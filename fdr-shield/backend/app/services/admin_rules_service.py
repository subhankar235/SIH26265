"""Admin-managed immutable automation rule versions."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateTransition, NotFound
from app.models.workflow import AutomationRule, AutomationRuleVersion
from app.models.user import User
from app.services.audit_service import record


async def list_rules(session: AsyncSession) -> list[dict]:
    rules = list((await session.scalars(select(AutomationRule).order_by(AutomationRule.rule_key))).all())
    result = []
    for rule in rules:
        versions = list((await session.scalars(select(AutomationRuleVersion)
            .where(AutomationRuleVersion.rule_id == rule.id)
            .order_by(AutomationRuleVersion.version.desc()).limit(20))).all())
        result.append({'id': rule.id, 'rule_key': rule.rule_key, 'description': rule.description,
            'versions': [{'id': v.id, 'version': v.version, 'policy': v.policy,
                'created_by': v.created_by, 'created_at': v.created_at} for v in versions]})
    return result


async def create_rule(session: AsyncSession, actor: User, rule_key: str, description: str, policy: dict) -> dict:
    if not isinstance(rule_key, str) or not isinstance(description, str):
        raise InvalidStateTransition('Rule key and description must be text.')
    key = rule_key.strip()
    if not key or len(key) > 100 or not isinstance(policy, dict):
        raise InvalidStateTransition('Provide a rule key (1–100 characters) and a JSON object policy.')
    exists = await session.scalar(select(AutomationRule.id).where(AutomationRule.rule_key == key))
    if exists:
        raise InvalidStateTransition('A rule with this key already exists; append a new version instead.')
    rule = AutomationRule(rule_key=key, description=description.strip())
    session.add(rule); await session.flush()
    version = AutomationRuleVersion(rule_id=rule.id, version=1, policy=policy, created_by=actor.id)
    session.add(version); await session.flush()
    await record(session, actor.id, 'automation_rule', rule.id, 'RULE_CREATED', '',
        {'rule_key': [None, key], 'version': [None, 1], 'policy': [None, policy]})
    return {'id': rule.id, 'rule_key': key, 'description': rule.description,
            'version': version.version, 'policy': version.policy}


async def append_version(session: AsyncSession, actor: User, rule_id: int, policy: dict) -> dict:
    rule = await session.get(AutomationRule, rule_id)
    if not rule:
        raise NotFound('Automation rule not found.')
    if not isinstance(policy, dict):
        raise InvalidStateTransition('Policy must be a JSON object.')
    latest = await session.scalar(select(AutomationRuleVersion).where(
        AutomationRuleVersion.rule_id == rule_id).order_by(AutomationRuleVersion.version.desc()).limit(1))
    version_no = (latest.version if latest else 0) + 1
    version = AutomationRuleVersion(rule_id=rule_id, version=version_no, policy=policy, created_by=actor.id)
    session.add(version); await session.flush()
    await record(session, actor.id, 'automation_rule', rule.id, 'RULE_VERSION_CREATED', '',
        {'version': [latest.version if latest else None, version_no],
         'policy': [latest.policy if latest else None, policy]})
    return {'id': rule.id, 'rule_key': rule.rule_key, 'version': version_no, 'policy': policy}
