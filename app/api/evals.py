from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.evals.dashboard import DASHBOARD_HTML

router = APIRouter(tags=["evals"])


class EvalCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=20000)
    expected_contains: str | None = Field(default=None, max_length=4000)
    enabled: bool = True


class EvalCaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    expected_contains: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None


class EvalFromRun(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expected_contains: str | None = Field(default=None, max_length=4000)


class EvalRunRequest(BaseModel):
    case_ids: list[str] | None = None


@router.get("/evals", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    return DASHBOARD_HTML


@router.get("/v1/evals/cases")
async def list_cases(request: Request):
    return await request.app.state.eval_repository.list_cases()


@router.post("/v1/evals/cases", status_code=201)
async def create_case(body: EvalCaseCreate, request: Request):
    return await request.app.state.eval_repository.create_case(**body.model_dump())


@router.patch("/v1/evals/cases/{case_id}")
async def update_case(case_id: str, body: EvalCaseUpdate, request: Request):
    result = await request.app.state.eval_repository.update_case(
        case_id, **body.model_dump(exclude_unset=True)
    )
    if result is None:
        raise HTTPException(404, detail={"code": "eval_case_not_found"})
    return result


@router.delete("/v1/evals/cases/{case_id}", status_code=204)
async def delete_case(case_id: str, request: Request):
    if not await request.app.state.eval_repository.delete_case(case_id):
        raise HTTPException(404, detail={"code": "eval_case_not_found"})
    return Response(status_code=204)


@router.post("/v1/evals/cases/from-run/{run_id}", status_code=201)
async def create_from_run(run_id: str, body: EvalFromRun, request: Request):
    result = await request.app.state.eval_repository.create_case_from_run(
        run_id, body.name, body.expected_contains
    )
    if result is None:
        raise HTTPException(404, detail={"code": "run_not_found"})
    return result


@router.post("/v1/evals/run")
async def run_evals(body: EvalRunRequest, request: Request):
    return await request.app.state.eval_service.run(body.case_ids)


@router.get("/v1/evals/runs")
async def list_runs(request: Request, limit: int = 20):
    return await request.app.state.eval_repository.list_runs(max(1, min(limit, 100)))


@router.get("/v1/evals/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    result = await request.app.state.eval_repository.get_run(run_id)
    if result is None:
        raise HTTPException(404, detail={"code": "eval_run_not_found"})
    return result
