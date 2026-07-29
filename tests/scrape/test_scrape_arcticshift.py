#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /tests/scrape/test_scrape_arcticshift.py                                            #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Tuesday July 28th 2026 08:45:00 pm                                                  #
# Modified   : Tuesday July 28th 2026 08:45:00 pm                                                  #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #
"""Integration tests for the Arctic Shift engine's rate handling.

Arctic Shift refuses work in two different ways and the difference is the whole point of
these tests. A 422 means too many requests are open at once, which the width of the
limiter controls. A 429 means the rolling request budget for the window is spent, which
width cannot buy back: inside a depleted window every request fails however few are in
flight. Reading a 429 as a width problem walks the limit to the floor for something that
only a clock can fix, which is what these tests exist to catch.

`EquilibriumLimiter` and `reset_wait` are exercised directly, since both are ordinary
objects with no I/O. The `_request` paths are exercised against a real local HTTP server
(see `conftest.ArchiveServer`) rather than against the live archive, because provoking a
429 there means exhausting a window shared with every other user of a free service.

``pytest-asyncio`` is not a project dependency, so each async test drives its coroutine
with ``asyncio.run`` from an ordinary test function, matching ``test_scrape_async``.

Run with:  pytest tests/scrape/test_scrape_arcticshift.py
"""
from typing import Any, Callable, List

import asyncio
import inspect
import logging
from datetime import datetime
from pathlib import Path

import aiohttp
import pytest

from ask_reddit.constants import (
    ARCTICSHIFT_HOLD_ROUNDS,
    ARCTICSHIFT_MAX_HOLD_ROUNDS,
    ARCTICSHIFT_MAX_RESET_WAIT,
    ARCTICSHIFT_RESUME_JITTER,
)
from ask_reddit.model import GenAIModel
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer
from ask_reddit.scrape_arcticshift import (
    ArcticShiftScraper,
    EquilibriumLimiter,
    reset_wait,
)

# ------------------------------------------------------------------------------------------------ #
# pylint: disable=missing-class-docstring, line-too-long, redefined-outer-name, protected-access
# mypy: ignore-errors
# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #
double_line = f"\n{100 * '='}"
single_line = f"\n{100 * '-'}"

# The 422 and 429 statuses are named rather than inlined, so a test reads as the distinction
# it is making rather than as two adjacent numbers.
TOO_MANY_OPEN = 422
WINDOW_SPENT = 429


# ------------------------------------------------------------------------------------------------ #
def log_start(cls_name: str, test_name: str) -> datetime:
    """Logs the start of a test and returns the start time."""
    start = datetime.now()
    logger.info(f"\n\nStarted {cls_name} {test_name} at {start.strftime('%I:%M:%S %p')}")
    logger.info(double_line)
    return start


# ------------------------------------------------------------------------------------------------ #
def log_end(cls_name: str, test_name: str, start: datetime) -> None:
    """Logs the completion of a test and its duration."""
    end = datetime.now()
    logger.info(
        f"\n\nCompleted {cls_name} {test_name} in "
        f"{round((end - start).total_seconds(), 1)} seconds"
    )
    logger.info(single_line)


# ------------------------------------------------------------------------------------------------ #
async def drain_round(limiter: EquilibriumLimiter, rounds: int = 1) -> None:
    """Report a full round of clean responses at the current width.

    The limiter widens once per round rather than once per success, and a round is as many
    successes as the current limit. Tests that need it to consider widening have to serve
    that many, so the counting lives here rather than being repeated.

    Args:
        limiter (EquilibriumLimiter): Limiter to report successes to.
        rounds (int): Number of full rounds to serve.
    """
    for _ in range(rounds):
        for _ in range(limiter.limit):
            await limiter.on_success()


# ------------------------------------------------------------------------------------------------ #
def build_scraper(
    session: aiohttp.ClientSession,
    directory: Path,
    subreddit: str,
    concurrency: int = 4,
    max_retries: int = 3,
    retry_backoff: float = 0.05,
) -> ArcticShiftScraper:
    """Builds a real scraper against a temporary corpus directory.

    The model, printer, and file manager are the production objects the CLI wires up. The
    retry backoff is shortened because these tests assert on which waits happen rather than
    on the production ramp's length, and the default would make the suite minutes long.

    Args:
        session (aiohttp.ClientSession): Open session the scraper will use.
        directory (Path): Output directory for any batch files.
        subreddit (str): Subreddit name the scraper is built for.
        concurrency (int): Ceiling handed to the limiter.
        max_retries (int): Attempts allowed per retriable request.
        retry_backoff (float): Base backoff seconds.

    Returns:
        ArcticShiftScraper: The constructed scraper.
    """
    file_manager = FileManager(
        source="reddit", topic=subreddit, file_location=str(directory)
    )
    return ArcticShiftScraper(
        scraper=session,
        model=GenAIModel(),
        printer=Printer(),
        subreddit=subreddit,
        months=1,
        filemanager=file_manager,
        concurrency=concurrency,
        max_retries=max_retries,
        retry_backoff=retry_backoff,
    )


# ------------------------------------------------------------------------------------------------ #
async def request_against(
    server: Any,
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    subreddit: str,
    **scraper_kwargs: Any,
) -> tuple:
    """Run one `_request` against the local archive and return the scraper and outcome.

    Only the base URL is redirected. The session, the retry loop, the limiter, and the
    response handling are all the production code under test.

    Args:
            server (Any): Scripted local archive to answer the request.
        monkeypatch (pytest.MonkeyPatch): Patcher used to redirect the base URL.
        directory (Path): Output directory for the scraper's file manager.
        subreddit (str): Subreddit name the scraper is built for.
        **scraper_kwargs (Any): Overrides forwarded to `build_scraper`.

    Returns:
        tuple: The scraper, the returned records or None, the raised error or None, and
            the elapsed seconds the call took.
    """
    async with server as base_url:
        monkeypatch.setattr(
            "ask_reddit.scrape_arcticshift.ARCTICSHIFT_BASE_URL", base_url
        )
        async with aiohttp.ClientSession() as session:
            scraper = build_scraper(
                session=session,
                directory=directory,
                subreddit=subreddit,
                **scraper_kwargs,
            )
            started = asyncio.get_running_loop().time()
            records, error = None, None
            try:
                records = await scraper._request("posts/search", {"subreddit": subreddit})
            except Exception as exc:  # noqa: BLE001 - the type is asserted by the caller
                error = exc
            elapsed = asyncio.get_running_loop().time() - started
            return scraper, records, error, elapsed


# ================================================================================================ #
#                                   WIDENING TOWARD EQUILIBRIUM                                    #
# ================================================================================================ #
class TestLimiterWidens:
    # ============================================================================================ #
    def test_opens_at_the_initial_width(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        limiter = EquilibriumLimiter(ceiling=16, initial=4)
        assert limiter.limit == 4, "limiter did not open where it was told to"
        assert limiter.luffs == 0, "a fresh limiter has not luffed"
        assert limiter.pauses == 0, "a fresh limiter has not paused"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_initial_width_is_clamped_into_the_ceiling_and_floor(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # A --concurrency of 1 must not be widened to the default initial of 4.
        assert EquilibriumLimiter(ceiling=1, initial=4).limit == 1, "opened above the ceiling"
        # A floor above the requested initial wins, or the limiter would open stalled.
        assert EquilibriumLimiter(ceiling=8, initial=1, floor=3).limit == 3, "opened below the floor"
        # A nonsensical ceiling is clamped rather than producing a limiter that never runs.
        assert EquilibriumLimiter(ceiling=0, initial=4).limit == 1, "ceiling was not clamped"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_widens_by_one_after_a_clean_round(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=16, initial=4)
            # One success short of a round must not move it, or the step is per-success.
            for _ in range(limiter.limit - 1):
                await limiter.on_success()
            assert limiter.limit == 4, "widened before a full round completed"
            await limiter.on_success()
            return limiter

        limiter = asyncio.run(scenario())
        assert limiter.limit == 5, "a clean round did not ease the limit out by one"
        assert limiter.high_water == 5, "high water did not follow the widening"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_never_widens_past_the_ceiling(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=5, initial=4)
            await drain_round(limiter, rounds=6)
            return limiter

        limiter = asyncio.run(scenario())
        assert limiter.limit == 5, "the user's --concurrency ceiling was exceeded"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ================================================================================================ #
#                                    LUFFING ON A 422 SIGNAL                                       #
# ================================================================================================ #
class TestLimiterLuffs:
    # ============================================================================================ #
    def test_a_luff_comes_in_one_notch_and_records_the_low_water(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            async with limiter.slot() as epoch:
                await limiter.on_throttle(epoch)
            return limiter

        limiter = asyncio.run(scenario())
        assert limiter.limit == 7, "a luff did not narrow the limit by one"
        assert limiter.luffs == 1, "the luff was not counted"
        assert limiter.low_water == 7, "low water did not follow the narrowing"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_never_narrows_below_the_floor(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=4, initial=2)
            for _ in range(6):
                async with limiter.slot() as epoch:
                    await limiter.on_throttle(epoch)
            return limiter

        limiter = asyncio.run(scenario())
        # A limiter that reached zero would stall the run outright, which is worse than
        # being slow, so the floor is a hard stop rather than a preference.
        assert limiter.limit == 1, "the limiter narrowed past its floor"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_stale_epoch_failures_do_not_narrow_again(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            # Eight requests are open together and all fail, which is what actually happens:
            # the limit trips for the fleet, not for one request. Without the epoch guard
            # the limiter would step down once per failure and walk to the floor for a
            # single event.
            async with limiter.slot() as epoch:
                for _ in range(8):
                    await limiter.on_throttle(epoch)
            return limiter

        limiter = asyncio.run(scenario())
        assert limiter.limit == 7, "one shared event narrowed the limit more than once"
        assert limiter.luffs == 1, "stale epoch failures were counted as separate luffs"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_failure_from_the_current_epoch_does_narrow(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            async with limiter.slot() as first:
                await limiter.on_throttle(first)
            # A request issued after the cut carries the new epoch, so its failure is
            # genuinely new information and must be acted on.
            async with limiter.slot() as second:
                await limiter.on_throttle(second)
            return limiter

        limiter = asyncio.run(scenario())
        assert limiter.limit == 6, "a fresh epoch failure was wrongly ignored"
        assert limiter.luffs == 2, "the second luff was not counted"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_hold_defers_widening_until_it_is_served(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> List[int]:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            async with limiter.slot() as epoch:
                await limiter.on_throttle(epoch)
            assert limiter.holding, "a luff did not cleat the limiter"

            widths = []
            for _ in range(ARCTICSHIFT_HOLD_ROUNDS):
                await drain_round(limiter)
                widths.append(limiter.limit)
            # The hold is now served, so the next clean round probes upward again.
            await drain_round(limiter)
            widths.append(limiter.limit)
            return widths

        widths = asyncio.run(scenario())
        assert widths[:-1] == [7] * ARCTICSHIFT_HOLD_ROUNDS, (
            f"limiter probed upward during its hold: {widths}"
        )
        assert widths[-1] == 8, "limiter never probed upward after serving its hold"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_repeat_luff_at_a_known_level_doubles_the_hold(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> List[int]:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            rounds_held = []
            for _ in range(3):
                # Luff at 8, serve the hold, climb back to 8, and luff there again. Each
                # repeat should buy a longer sit before the next look.
                async with limiter.slot() as epoch:
                    await limiter.on_throttle(epoch)
                held = 0
                while limiter.holding:
                    await drain_round(limiter)
                    held += 1
                rounds_held.append(held)
                # Widen back to the level that luffed, so the next luff is a repeat.
                while limiter.limit < 8:
                    await drain_round(limiter)
            return rounds_held

        rounds_held = asyncio.run(scenario())
        # Each repeat at a level already known to be too far doubles the wait, which is what
        # turns the search into a settle instead of a hunt.
        assert rounds_held == [
            ARCTICSHIFT_HOLD_ROUNDS,
            ARCTICSHIFT_HOLD_ROUNDS * 2,
            ARCTICSHIFT_HOLD_ROUNDS * 4,
        ], f"the hold did not double on repeat luffs: {rounds_held}"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_luff_at_a_new_level_resets_the_hold(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> int:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            # Luff at 8, then again at 7 without climbing back. The second is a level the
            # limiter has not seen fail before, so it carries no accumulated penalty.
            async with limiter.slot() as first:
                await limiter.on_throttle(first)
            async with limiter.slot() as second:
                await limiter.on_throttle(second)
            held = 0
            while limiter.holding:
                await drain_round(limiter)
                held += 1
            return held

        held = asyncio.run(scenario())
        assert held == ARCTICSHIFT_HOLD_ROUNDS, (
            f"a luff at an unseen level inherited a doubled hold: {held} rounds"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_hold_doubling_stops_at_the_cap(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> int:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            # Enough repeats at one level to run the doubling well past the cap. Without a
            # ceiling on it, a long run would eventually stop probing altogether.
            repeats = 12
            for iteration in range(repeats):
                async with limiter.slot() as epoch:
                    await limiter.on_throttle(epoch)
                if iteration == repeats - 1:
                    # The last luff is left cleated, since the hold it set is the thing
                    # being measured. Climbing back would serve it first.
                    break
                # Climbing back to the level that luffs makes the next luff a repeat. The
                # hold is cleared directly rather than served, because serving a doubled
                # hold honestly would take thousands of rounds and prove nothing extra.
                while limiter.limit < 8:
                    limiter._hold_remaining = 0
                    await drain_round(limiter)
            held = 0
            while limiter.holding:
                await drain_round(limiter)
                held += 1
            return held

        held = asyncio.run(scenario())
        assert held == ARCTICSHIFT_MAX_HOLD_ROUNDS, (
            f"hold grew past its cap of {ARCTICSHIFT_MAX_HOLD_ROUNDS}: {held} rounds"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_reset_marks_clears_reporting_but_keeps_the_settled_width(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            async with limiter.slot() as epoch:
                await limiter.on_throttle(epoch)
            limiter.pause(0.01)
            limiter.reset_marks()
            return limiter

        limiter = asyncio.run(scenario())
        # What the service sustained a minute ago is the best guess for the next span, so
        # only the per-span reporting resets.
        assert limiter.limit == 7, "reset_marks discarded the settled width"
        assert limiter.luffs == 0, "luff count was not reset for the new span"
        assert limiter.pauses == 0, "pause count was not reset for the new span"
        assert limiter.paused_seconds == 0.0, "paused seconds were not reset for the new span"
        assert limiter.low_water == 7, "low water did not rebase on the settled width"
        assert limiter.high_water == 7, "high water did not rebase on the settled width"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ================================================================================================ #
#                                  PAUSING ON A SPENT WINDOW                                       #
# ================================================================================================ #
class TestLimiterPauses:
    # ============================================================================================ #
    def test_a_pause_leaves_the_settled_width_alone(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> EquilibriumLimiter:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            for _ in range(5):
                limiter.pause(0.01)
            return limiter

        limiter = asyncio.run(scenario())
        # This is the whole point: a spent window says nothing about how many connections
        # the service wants open, so the width found by feel must survive it.
        assert limiter.limit == 8, "a spent window narrowed the width it cannot speak to"
        assert limiter.luffs == 0, "a spent window was miscounted as a luff"
        assert limiter.low_water == 8, "a spent window moved the low water mark"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_longer_deadline_extends_the_pause(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> tuple:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            first = limiter.pause(5.0)
            longer = limiter.pause(6.0)
            return limiter, first, longer

        limiter, first, longer = asyncio.run(scenario())
        assert first == pytest.approx(5.0, abs=0.05), "the first pause was not taken whole"
        # Only the part past the existing deadline is new waiting, so the extension is the
        # difference rather than the full six seconds.
        assert longer == pytest.approx(1.0, abs=0.05), (
            f"extending double counted the overlap: added {longer}s"
        )
        assert limiter.paused_seconds == pytest.approx(6.0, abs=0.05), (
            "total paused time does not match the final deadline"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_shorter_deadline_does_not_cut_the_pause_short(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> tuple:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            limiter.pause(5.0)
            # Concurrent 429s all describe the same window seen from slightly different
            # moments. A straggler reporting a shorter remainder must not release the fleet
            # early, or the refilled window is spent again on arrival.
            shorter = limiter.pause(4.8)
            return limiter, shorter

        limiter, shorter = asyncio.run(scenario())
        assert shorter == 0.0, f"a shorter view of the same window cut the wait short: {shorter}s"
        assert limiter.pauses == 1, "a no-op extension was counted as a new pause"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_non_positive_pause_is_ignored(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> tuple:
            limiter = EquilibriumLimiter(ceiling=16, initial=8)
            return limiter, limiter.pause(0.0), limiter.pause(-3.0)

        limiter, zero, negative = asyncio.run(scenario())
        assert zero == 0.0, "a zero pause was treated as a wait"
        assert negative == 0.0, "a negative pause was treated as a wait"
        assert limiter.pauses == 0, "a no-op pause was counted"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_the_gate_holds_every_request_until_the_window_refills(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        held_for = 0.4

        async def scenario() -> List[float]:
            limiter = EquilibriumLimiter(ceiling=8, initial=8)
            limiter.pause(held_for)
            began = asyncio.get_running_loop().time()

            async def take_a_slot() -> float:
                async with limiter.slot():
                    return asyncio.get_running_loop().time() - began

            # More requests than the width, so this also proves the gate runs before the
            # slot is taken: a paused fleet must hold no slots at all.
            return await asyncio.gather(*(take_a_slot() for _ in range(12)))

        waits = asyncio.run(scenario())
        assert min(waits) >= held_for, (
            f"a request was issued into a window still spent: waited {min(waits):.3f}s"
        )
        # Released across the jitter window rather than all on the same instant, or the
        # refilled window is spent again in one burst by the fleet waking together.
        assert max(waits) <= held_for + ARCTICSHIFT_RESUME_JITTER + 1.0, (
            f"the gate held far longer than the deadline: waited {max(waits):.3f}s"
        )
        assert len(set(round(wait, 3) for wait in waits)) > 1, (
            "every request resumed on the same instant, so the release was not jittered"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_the_gate_is_transparent_when_no_window_is_spent(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> float:
            limiter = EquilibriumLimiter(ceiling=8, initial=8)
            began = asyncio.get_running_loop().time()
            async with limiter.slot():
                pass
            return asyncio.get_running_loop().time() - began

        elapsed = asyncio.run(scenario())
        assert elapsed < 0.1, f"an unpaused limiter delayed a request by {elapsed:.3f}s"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_the_width_still_bounds_how_many_run_at_once(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        async def scenario() -> int:
            limiter = EquilibriumLimiter(ceiling=3, initial=3)
            peak = 0
            in_flight = 0

            async def one_request() -> None:
                nonlocal peak, in_flight
                async with limiter.slot():
                    in_flight += 1
                    peak = max(peak, in_flight)
                    await asyncio.sleep(0.01)
                    in_flight -= 1

            await asyncio.gather(*(one_request() for _ in range(15)))
            return peak

        peak = asyncio.run(scenario())
        assert peak <= 3, f"{peak} requests were open at once against a width of 3"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ================================================================================================ #
#                                   READING THE RESET HEADER                                       #
# ================================================================================================ #
class TestResetWait:
    # ============================================================================================ #
    def test_the_services_own_reset_is_preferred_to_a_guess(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert reset_wait({"x-ratelimit-reset": "8"}, 30.0) == 8.0, (
            "the exact reset the service published was ignored in favour of a backoff"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_retry_after_is_honoured_when_no_reset_is_sent(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert reset_wait({"Retry-After": "12"}, 30.0) == 12.0, "Retry-After was not honoured"
        # The archive's own header wins when both are present, since a proxy's view is the
        # coarser of the two.
        assert reset_wait({"x-ratelimit-reset": "3", "Retry-After": "12"}, 30.0) == 3.0, (
            "a proxy's Retry-After overrode the archive's own reset"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_missing_headers_fall_back_to_the_backoff(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert reset_wait({}, 30.0) == 30.0, "a headerless response did not fall back"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_an_http_date_falls_back_rather_than_raising(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Retry-After is legitimately either a duration or an HTTP date, and the date form
        # must not take down the request that received it.
        assert reset_wait({"Retry-After": "Wed, 29 Jul 2026 00:30:52 GMT"}, 30.0) == 30.0, (
            "an HTTP date was not handled"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_non_duration_value_falls_back(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # `x-ratelimit-reset-at` is epoch milliseconds. Read as a duration it would park the
        # run for fifty thousand years, so the cap is what keeps a header mix-up survivable.
        assert reset_wait({"x-ratelimit-reset": "1785285060000"}, 30.0) == 30.0, (
            "an absolute timestamp was accepted as a duration"
        )
        assert reset_wait({"x-ratelimit-reset": "not-a-number"}, 30.0) == 30.0, (
            "unparseable header was not handled"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_the_cap_is_the_boundary_it_claims_to_be(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert reset_wait({"x-ratelimit-reset": str(ARCTICSHIFT_MAX_RESET_WAIT)}, 30.0) == (
            ARCTICSHIFT_MAX_RESET_WAIT
        ), "a wait exactly at the cap was rejected"
        assert reset_wait({"x-ratelimit-reset": str(ARCTICSHIFT_MAX_RESET_WAIT + 1)}, 30.0) == 30.0, (
            "a wait past the cap was accepted"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_zero_or_negative_reset_falls_back(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # A zero would mean retrying instantly into the same spent window.
        assert reset_wait({"x-ratelimit-reset": "0"}, 30.0) == 30.0, "a zero reset was accepted"
        assert reset_wait({"x-ratelimit-reset": "-5"}, 30.0) == 30.0, "a negative reset was accepted"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ================================================================================================ #
#                              THE REQUEST LOOP AGAINST A REAL SERVER                              #
# ================================================================================================ #
@pytest.mark.integration
class TestRequestThrottleHandling:
    # ============================================================================================ #
    def test_a_clean_response_returns_its_records_and_widens_nothing_prematurely(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        throttled_page: List[dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        server = archive_server([scripted_response(status=200, data=throttled_page)])
        scraper, records, error, _ = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit)
        )

        assert error is None, f"a clean response raised {error!r}"
        assert records == throttled_page, "the payload's data was not returned intact"
        assert len(server.requests) == 1, f"a clean response was retried {len(server.requests)} times"
        assert not scraper._throttles, "a clean response was counted as throttling"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_too_many_open_narrows_the_width_and_does_not_pause(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        throttled_page: List[dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        server = archive_server(
            [
                scripted_response(status=TOO_MANY_OPEN),
                scripted_response(status=200, data=throttled_page),
            ]
        )
        scraper, records, error, _ = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit, concurrency=4)
        )

        assert error is None, f"a recoverable 422 raised {error!r}"
        assert records == throttled_page, "the retry did not return the eventual payload"
        assert scraper._throttles[TOO_MANY_OPEN] == 1, "the 422 was not counted under its status"
        # 422 is the one signal width can act on, so this is where luffing belongs.
        assert scraper._limiter.luffs == 1, "a 422 did not luff the limiter"
        assert scraper._limiter.limit == 3, "a 422 did not narrow the width by one"
        assert scraper._limiter.pauses == 0, "a 422 wrongly paused the whole fleet"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_spent_window_pauses_and_holds_the_width(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        throttled_page: List[dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        server = archive_server(
            [
                scripted_response(status=WINDOW_SPENT, headers={"x-ratelimit-reset": "1"}),
                scripted_response(status=200, data=throttled_page),
            ]
        )
        scraper, records, error, _ = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit, concurrency=4)
        )

        assert error is None, f"a recoverable 429 raised {error!r}"
        assert records == throttled_page, "the retry did not return the eventual payload"
        assert scraper._throttles[WINDOW_SPENT] == 1, "the 429 was not counted under its status"
        # The regression this whole change exists for: 28 of these in one span used to walk
        # the width from 16 down to 1 for something width cannot fix.
        assert scraper._limiter.luffs == 0, "a spent window was read as a width problem"
        assert scraper._limiter.limit == 4, "a spent window narrowed the settled width"
        assert scraper._limiter.pauses == 1, "a spent window did not pause the fleet"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_the_retry_waits_as_long_as_the_service_asked(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        throttled_page: List[dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        reset_seconds = 1.5
        server = archive_server(
            [
                scripted_response(
                    status=WINDOW_SPENT, headers={"x-ratelimit-reset": str(reset_seconds)}
                ),
                scripted_response(status=200, data=throttled_page),
            ]
        )
        # The backoff is far shorter than the reset, so meeting the reset proves the header
        # drove the wait rather than the ramp happening to be long enough.
        scraper, records, error, _ = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit, retry_backoff=0.01)
        )

        assert error is None, f"a recoverable 429 raised {error!r}"
        assert records == throttled_page, "the retry did not return the eventual payload"
        assert len(server.requests) == 2, f"expected one retry, saw {len(server.requests)} requests"
        gap = server.requests[1][1] - server.requests[0][1]
        assert gap >= reset_seconds, (
            f"retried into a window with {reset_seconds}s still to run after only {gap:.2f}s"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_server_fault_retries_without_touching_the_limiter(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        throttled_page: List[dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        server = archive_server(
            [
                scripted_response(status=503),
                scripted_response(status=200, data=throttled_page),
            ]
        )
        scraper, records, error, _ = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit, concurrency=4)
        )

        assert error is None, f"a transient 503 raised {error!r}"
        assert records == throttled_page, "the retry did not return the eventual payload"
        assert scraper._throttles[503] == 1, "the fault was not counted"
        # A transient fault on one request speaks to neither the width nor the window, so
        # neither the limit nor the rest of the fleet should be disturbed for it.
        assert scraper._limiter.luffs == 0, "a server fault narrowed the width"
        assert scraper._limiter.limit == 4, "a server fault moved the settled width"
        assert scraper._limiter.pauses == 0, "a server fault paused the whole fleet"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_the_two_refusals_are_counted_separately(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        throttled_page: List[dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        server = archive_server(
            [
                scripted_response(status=TOO_MANY_OPEN),
                scripted_response(status=WINDOW_SPENT, headers={"x-ratelimit-reset": "1"}),
                scripted_response(status=200, data=throttled_page),
            ]
        )
        scraper, records, error, _ = asyncio.run(
            request_against(
                server, monkeypatch, tmp_path, subreddit, concurrency=4, max_retries=4
            )
        )

        assert error is None, f"a recoverable sequence raised {error!r}"
        assert records == throttled_page, "the retries did not return the eventual payload"
        # Collapsing these into one total throws away the only diagnostic the span warning
        # carries, which is how the original misdiagnosis went unnoticed.
        assert scraper._throttles[TOO_MANY_OPEN] == 1, "the 422 was not counted separately"
        assert scraper._throttles[WINDOW_SPENT] == 1, "the 429 was not counted separately"
        assert scraper._limiter.luffs == 1, "only the 422 should have luffed"
        assert scraper._limiter.pauses == 1, "only the 429 should have paused"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_exhausting_the_retries_raises(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        server = archive_server(
            [scripted_response(status=WINDOW_SPENT, headers={"x-ratelimit-reset": "1"})]
        )
        scraper, _, error, _ = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit, max_retries=2)
        )

        # A span that cannot be fetched has to surface, or the run reports a corpus it does
        # not have.
        assert isinstance(error, aiohttp.ClientResponseError), (
            f"an unrecoverable throttle raised {error!r} instead of a response error"
        )
        assert error.status == WINDOW_SPENT, f"raised on status {error.status}"
        assert len(server.requests) == 2, (
            f"max_retries=2 made {len(server.requests)} attempts"
        )
        assert scraper._throttles[WINDOW_SPENT] == 2, "not every attempt was counted"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_malformed_request_raises_at_once(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        server = archive_server([scripted_response(status=400)])
        scraper, _, error, elapsed = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit, max_retries=5)
        )

        assert isinstance(error, aiohttp.ClientResponseError), (
            f"a malformed request raised {error!r} instead of a response error"
        )
        assert error.status == 400, f"raised on status {error.status}"
        # A 400 would fail identically however often it were repeated, so retrying it only
        # burns the budget a genuine throttle will need.
        assert len(server.requests) == 1, (
            f"a malformed request was retried {len(server.requests)} times"
        )
        assert not scraper._throttles, "a malformed request was counted as throttling"
        assert scraper._limiter.luffs == 0, "a malformed request narrowed the width"
        assert scraper._limiter.pauses == 0, "a malformed request paused the fleet"
        assert elapsed < 1.0, f"a malformed request took {elapsed:.2f}s to fail"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_a_success_after_throttling_still_drives_widening(
        self,
        archive_server: Callable[..., Any],
        scripted_response: type,
        throttled_page: List[dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        subreddit: str,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Width of one, so a single served response is a full clean round. The limiter is
        # cleated by the preceding luff, so the round must be absorbed by the hold rather
        # than immediately re-probing the level that just failed.
        server = archive_server(
            [
                scripted_response(status=TOO_MANY_OPEN),
                scripted_response(status=200, data=throttled_page),
            ]
        )
        scraper, records, error, _ = asyncio.run(
            request_against(server, monkeypatch, tmp_path, subreddit, concurrency=1)
        )

        assert error is None, f"a recoverable 422 raised {error!r}"
        assert records == throttled_page, "the retry did not return the eventual payload"
        assert scraper._limiter.limit == 1, "the limiter re-probed a level it had just luffed at"
        assert scraper._limiter.holding, "a luff did not cleat the limiter"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)
