import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.fields.email_field import NormalizedEmail
from app.core.settings import settings

email = TypeAdapter(NormalizedEmail)


@pytest.mark.parametrize('value', ['a@nas.lan', 'a@corp.internal', 'Anna@Corp.RU'])
def test_ordinary_and_non_reserved_internal_domains_pass(value):
    assert email.validate_python(f'  {value} ') == value.lower()


# `.test` is not listed: conftest turns on email-validator's test environment, which allows it.
@pytest.mark.parametrize('value', ['a@team.local', 'a@nas.home.arpa'])
def test_special_use_domains_are_rejected_by_default(value):
    with pytest.raises(ValidationError):
        email.validate_python(value)


@pytest.mark.parametrize('value', ['a@team.local', 'A@Hearfolio.Test', 'a@nas.home.arpa'])
def test_special_use_domains_pass_when_allowed(monkeypatch, value):
    monkeypatch.setattr(settings, 'allow_local_email_domains', True)
    assert email.validate_python(value) == value.lower()


@pytest.mark.parametrize('value', ['a@local', 'a@localhost', 'a@onion', 'not-an-email', 'a@@team.local', 'a@.local'])
def test_allowing_local_domains_keeps_every_other_rule(monkeypatch, value):
    monkeypatch.setattr(settings, 'allow_local_email_domains', True)
    with pytest.raises(ValidationError):
        email.validate_python(value)
