"""Tests for Glances config flow."""
from unittest.mock import MagicMock

from glances_api.exceptions import (
    GlancesApiAuthorizationError,
    GlancesApiConnectionError,
)
import pytest

from homeassistant import config_entries
from homeassistant.components import glances
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import HA_SENSOR_DATA, MOCK_USER_INPUT

from tests.common import MockConfigEntry, patch


@pytest.fixture(autouse=True)
def glances_setup_fixture():
    """Mock glances entry setup."""
    with patch("homeassistant.components.glances.async_setup_entry", return_value=True):
        yield


async def test_form(hass: HomeAssistant) -> None:
    """Test config entry configured successfully."""

    result = await hass.config_entries.flow.async_init(
        glances.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_USER_INPUT
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "0.0.0.0:61208"
    assert result["data"] == MOCK_USER_INPUT


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (GlancesApiAuthorizationError, "invalid_auth"),
        (GlancesApiConnectionError, "cannot_connect"),
    ],
)
async def test_form_fails(
    hass: HomeAssistant, error: Exception, message: str, mock_api: MagicMock
) -> None:
    """Test flow fails when api exception is raised."""

    mock_api.return_value.get_ha_sensor_data.side_effect = [error, HA_SENSOR_DATA]
    result = await hass.config_entries.flow.async_init(
        glances.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_USER_INPUT
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": message}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_USER_INPUT
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_form_already_configured(hass: HomeAssistant) -> None:
    """Test host is already configured."""
    entry = MockConfigEntry(domain=glances.DOMAIN, data=MOCK_USER_INPUT)
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        glances.DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_USER_INPUT
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
