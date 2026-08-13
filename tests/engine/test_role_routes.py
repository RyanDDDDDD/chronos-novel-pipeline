"""角色路由：engine 只挂 REST，不挂 /ws（浏览器只连 Gateway）；combined 挂 /ws。"""
import pytest

pytest.importorskip("fastapi")
from api.routes import register_routes
from api.services.gateway_port import GatewayRole
from fastapi import FastAPI


def test_engine_role_has_no_ws_route():
    app = FastAPI()
    register_routes(app, role=GatewayRole.ENGINE)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/ws" not in paths


def test_combined_role_has_ws():
    app = FastAPI()
    register_routes(app, role=GatewayRole.COMBINED)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/ws" in paths  # 静态视 DIST_DIR 是否存在,不强断言
