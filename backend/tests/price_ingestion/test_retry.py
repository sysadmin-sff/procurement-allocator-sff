"""Tests for app.price_ingestion.retry — exponential backoff on
openai.RateLimitError, see ADR-0022 §2. Up to 3 attempts (1s/2s/4s delay
between retries), isolated per call: exhausting retries raises
RetryExhaustedError instead of propagating RateLimitError, so the caller
can degrade a single line instead of failing the whole batch."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import RateLimitError

from app.price_ingestion.retry import RetryExhaustedError, call_with_retry


def _rate_limit_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/x")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def test_succeeds_on_first_attempt_without_sleeping():
    fn = MagicMock(return_value="ok")

    with patch("app.price_ingestion.retry.time.sleep") as mock_sleep:
        result = call_with_retry(fn)

    assert result == "ok"
    fn.assert_called_once()
    mock_sleep.assert_not_called()


def test_succeeds_on_second_attempt_after_one_backoff_sleep():
    fn = MagicMock(side_effect=[_rate_limit_error(), "ok"])

    with patch("app.price_ingestion.retry.time.sleep") as mock_sleep:
        result = call_with_retry(fn)

    assert result == "ok"
    assert fn.call_count == 2
    mock_sleep.assert_called_once_with(1)


def test_succeeds_on_third_attempt_after_two_backoff_sleeps():
    fn = MagicMock(side_effect=[_rate_limit_error(), _rate_limit_error(), "ok"])

    with patch("app.price_ingestion.retry.time.sleep") as mock_sleep:
        result = call_with_retry(fn)

    assert result == "ok"
    assert fn.call_count == 3
    assert mock_sleep.call_args_list == [((1,),), ((2,),)]


def test_raises_retry_exhausted_after_three_failed_attempts():
    fn = MagicMock(side_effect=[_rate_limit_error(), _rate_limit_error(), _rate_limit_error()])

    with patch("app.price_ingestion.retry.time.sleep") as mock_sleep:
        with pytest.raises(RetryExhaustedError):
            call_with_retry(fn)

    assert fn.call_count == 3
    assert mock_sleep.call_args_list == [((1,),), ((2,),)]


def test_non_rate_limit_error_propagates_immediately_without_retry():
    fn = MagicMock(side_effect=ValueError("boom"))

    with patch("app.price_ingestion.retry.time.sleep") as mock_sleep:
        with pytest.raises(ValueError):
            call_with_retry(fn)

    fn.assert_called_once()
    mock_sleep.assert_not_called()
