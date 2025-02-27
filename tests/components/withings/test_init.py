"""Tests for the Withings component."""
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse

from freezegun.api import FrozenDateTimeFactory
import pytest
import voluptuous as vol
from withings_api.common import AuthFailedException, NotifyAppli, UnauthorizedException

from homeassistant import config_entries
from homeassistant.components.webhook import async_generate_url
from homeassistant.components.withings import CONFIG_SCHEMA, async_setup
from homeassistant.components.withings.const import CONF_USE_WEBHOOK, DOMAIN
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import call_webhook, enable_webhooks, setup_integration
from .conftest import USER_ID, WEBHOOK_ID

from tests.common import MockConfigEntry, async_fire_time_changed
from tests.typing import ClientSessionGenerator


def config_schema_validate(withings_config) -> dict:
    """Assert a schema config succeeds."""
    hass_config = {DOMAIN: withings_config}

    return CONFIG_SCHEMA(hass_config)


def config_schema_assert_fail(withings_config) -> None:
    """Assert a schema config will fail."""
    with pytest.raises(vol.MultipleInvalid):
        config_schema_validate(withings_config)


def test_config_schema_basic_config() -> None:
    """Test schema."""
    config_schema_validate(
        {
            CONF_CLIENT_ID: "my_client_id",
            CONF_CLIENT_SECRET: "my_client_secret",
            CONF_USE_WEBHOOK: True,
        }
    )


def test_config_schema_client_id() -> None:
    """Test schema."""
    config_schema_assert_fail(
        {CONF_CLIENT_SECRET: "my_client_secret", CONF_CLIENT_ID: ""}
    )
    config_schema_validate(
        {CONF_CLIENT_SECRET: "my_client_secret", CONF_CLIENT_ID: "my_client_id"}
    )


def test_config_schema_client_secret() -> None:
    """Test schema."""
    config_schema_assert_fail({CONF_CLIENT_ID: "my_client_id", CONF_CLIENT_SECRET: ""})
    config_schema_validate(
        {CONF_CLIENT_ID: "my_client_id", CONF_CLIENT_SECRET: "my_client_secret"}
    )


def test_config_schema_use_webhook() -> None:
    """Test schema."""
    config_schema_validate(
        {CONF_CLIENT_ID: "my_client_id", CONF_CLIENT_SECRET: "my_client_secret"}
    )
    config = config_schema_validate(
        {
            CONF_CLIENT_ID: "my_client_id",
            CONF_CLIENT_SECRET: "my_client_secret",
            CONF_USE_WEBHOOK: True,
        }
    )
    assert config[DOMAIN][CONF_USE_WEBHOOK] is True
    config = config_schema_validate(
        {
            CONF_CLIENT_ID: "my_client_id",
            CONF_CLIENT_SECRET: "my_client_secret",
            CONF_USE_WEBHOOK: False,
        }
    )
    assert config[DOMAIN][CONF_USE_WEBHOOK] is False
    config_schema_assert_fail(
        {
            CONF_CLIENT_ID: "my_client_id",
            CONF_CLIENT_SECRET: "my_client_secret",
            CONF_USE_WEBHOOK: "A",
        }
    )


async def test_async_setup_no_config(hass: HomeAssistant) -> None:
    """Test method."""
    hass.async_create_task = MagicMock()

    await async_setup(hass, {})

    hass.async_create_task.assert_not_called()


async def test_data_manager_webhook_subscription(
    hass: HomeAssistant,
    withings: AsyncMock,
    disable_webhook_delay,
    webhook_config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    """Test data manager webhook subscriptions."""
    await enable_webhooks(hass)
    await setup_integration(hass, webhook_config_entry)
    await hass_client_no_auth()
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert withings.async_notify_subscribe.call_count == 4

    webhook_url = "http://example.local:8123/api/webhook/55a7335ea8dee830eed4ef8f84cda8f6d80b83af0847dc74032e86120bffed5e"

    withings.async_notify_subscribe.assert_any_call(webhook_url, NotifyAppli.WEIGHT)
    withings.async_notify_subscribe.assert_any_call(
        webhook_url, NotifyAppli.CIRCULATORY
    )
    withings.async_notify_subscribe.assert_any_call(webhook_url, NotifyAppli.ACTIVITY)
    withings.async_notify_subscribe.assert_any_call(webhook_url, NotifyAppli.SLEEP)

    withings.async_notify_revoke.assert_any_call(webhook_url, NotifyAppli.BED_IN)
    withings.async_notify_revoke.assert_any_call(webhook_url, NotifyAppli.BED_OUT)


async def test_webhook_subscription_polling_config(
    hass: HomeAssistant,
    withings: AsyncMock,
    disable_webhook_delay,
    polling_config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test webhook subscriptions not run when polling."""
    await setup_integration(hass, polling_config_entry)
    await hass_client_no_auth()
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert withings.notify_revoke.call_count == 0
    assert withings.notify_subscribe.call_count == 0
    assert withings.notify_list.call_count == 0


@pytest.mark.parametrize(
    "method",
    [
        "PUT",
        "HEAD",
    ],
)
async def test_requests(
    hass: HomeAssistant,
    withings: AsyncMock,
    webhook_config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    method: str,
    disable_webhook_delay,
) -> None:
    """Test we handle request methods Withings sends."""
    await enable_webhooks(hass)
    await setup_integration(hass, webhook_config_entry)
    client = await hass_client_no_auth()
    webhook_url = async_generate_url(hass, WEBHOOK_ID)

    response = await client.request(
        method=method,
        path=urlparse(webhook_url).path,
    )
    assert response.status == 200


async def test_webhooks_request_data(
    hass: HomeAssistant,
    withings: AsyncMock,
    webhook_config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    disable_webhook_delay,
) -> None:
    """Test calling a webhook requests data."""
    await enable_webhooks(hass)
    await setup_integration(hass, webhook_config_entry)
    client = await hass_client_no_auth()

    assert withings.async_measure_get_meas.call_count == 1

    await call_webhook(
        hass,
        WEBHOOK_ID,
        {"userid": USER_ID, "appli": NotifyAppli.WEIGHT},
        client,
    )
    assert withings.async_measure_get_meas.call_count == 2


@pytest.mark.parametrize(
    "error",
    [
        UnauthorizedException(401),
        AuthFailedException(500),
    ],
)
async def test_triggering_reauth(
    hass: HomeAssistant,
    withings: AsyncMock,
    polling_config_entry: MockConfigEntry,
    error: Exception,
) -> None:
    """Test triggering reauth."""
    await setup_integration(hass, polling_config_entry)

    withings.async_measure_get_meas.side_effect = error
    future = dt_util.utcnow() + timedelta(minutes=10)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()

    assert len(flows) == 1
    flow = flows[0]
    assert flow["step_id"] == "reauth_confirm"
    assert flow["handler"] == DOMAIN
    assert flow["context"]["source"] == config_entries.SOURCE_REAUTH


@pytest.mark.parametrize(
    ("config_entry"),
    [
        MockConfigEntry(
            domain=DOMAIN,
            unique_id="123",
            data={
                "token": {"userid": 123},
                "profile": "henk",
                "use_webhook": False,
                "webhook_id": "3290798afaebd28519c4883d3d411c7197572e0cc9b8d507471f59a700a61a55",
            },
        ),
        MockConfigEntry(
            domain=DOMAIN,
            unique_id="123",
            data={
                "token": {"userid": 123},
                "profile": "henk",
                "use_webhook": False,
            },
        ),
    ],
)
async def test_config_flow_upgrade(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test config flow upgrade."""
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(config_entry.entry_id)

    assert entry.unique_id == "123"
    assert entry.data["token"]["userid"] == 123
    assert CONF_WEBHOOK_ID in entry.data
    assert entry.options == {
        "use_webhook": False,
    }


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        [{"userid": 0, "appli": NotifyAppli.WEIGHT.value}, 0],  # Success
        [{"userid": None, "appli": 1}, 0],  # Success, we ignore the user_id.
        [{}, 12],  # No request body.
        [{"userid": "GG"}, 20],  # appli not provided.
        [{"userid": 0}, 20],  # appli not provided.
        [{"userid": 0, "appli": 99}, 21],  # Invalid appli.
        [
            {"userid": 11, "appli": NotifyAppli.WEIGHT.value},
            0,
        ],  # Success, we ignore the user_id
    ],
)
async def test_webhook_post(
    hass: HomeAssistant,
    withings: AsyncMock,
    webhook_config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    disable_webhook_delay,
    body: dict[str, Any],
    expected_code: int,
    current_request_with_host: None,
) -> None:
    """Test webhook callback."""
    await enable_webhooks(hass)
    await setup_integration(hass, webhook_config_entry)
    client = await hass_client_no_auth()
    webhook_url = async_generate_url(hass, WEBHOOK_ID)

    resp = await client.post(urlparse(webhook_url).path, data=body)

    # Wait for remaining tasks to complete.
    await hass.async_block_till_done()

    data = await resp.json()
    resp.close()

    assert data["code"] == expected_code
