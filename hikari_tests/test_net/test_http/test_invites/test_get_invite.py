#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © Nekoka.tt 2019
#
# This file is part of Hikari.
#
# Hikari is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Hikari is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Hikari. If not, see <https://www.gnu.org/licenses/>.

import asynctest
import pytest


@pytest.fixture()
async def http_client(event_loop):
    from hikari_tests.test_net.test_http import ClientMock

    return ClientMock(token="foobarsecret", loop=event_loop)


@pytest.mark.asyncio
async def test_get_invite_without_counts(http_client):
    http_client.request = asynctest.CoroutineMock()
    await http_client.get_invite("424242")
    http_client.request.assert_awaited_once_with("get", "/invites/{invite_code}", invite_code="424242", query={})


@pytest.mark.asyncio
async def test_get_invite_with_counts(http_client):
    http_client.request = asynctest.CoroutineMock()
    await http_client.get_invite("424242", with_counts=True)
    http_client.request.assert_awaited_once_with(
        "get", "/invites/{invite_code}", invite_code="424242", query={"with_counts": True}
    )
