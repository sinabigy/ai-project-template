"""Tests for the ai-* tools. Standard library only.

Each test works on a fresh copy of the template in a temporary directory, so the template
itself is never modified. Run: python3 -m unittest discover -s tools/tests
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TEMPLATE / "tools"))
import _ailib as L  # noqa: E402

HAS_GIT = shutil.which("git") is not None


def _ignore(dirpath, names):
    rel = Path(dirpath).resolve().relative_to(TEMPLATE).as_posix()
    out = {n for n in names if n in (".git", "__pycache__")}
    if rel in (".ai/runtime", ".ai/map"):
        out |= {n for n in names if n != ".gitkeep"}
    if rel.startswith(".ai/tasks/") or rel == ".ai/context/summaries":
        out |= {n for n in names if n.endswith(".json")}
    return out


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Repo:
    def __init__(self, root: Path, env: dict | None = None):
        self.root = root
        self.env = {k: v for k, v in os.environ.items() if k != "AI_TOOLS_DISABLE"}
        self.env.update(env or {})

    def run(self, tool: str, *args, tools_root: Path | None = None) -> subprocess.CompletedProcess:
        script = (tools_root or self.root) / "tools" / tool
        return subprocess.run([sys.executable, str(script), *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=120)

    def ok(self, tool: str, *args, **kw) -> subprocess.CompletedProcess:
        r = self.run(tool, *args, **kw)
        if r.returncode != 0:
            raise AssertionError(f"{tool} {args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
        return r

    def json(self, rel: str):
        return json.loads((self.root / rel).read_text())

    def write_json(self, rel: str, data) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))

    def check(self, *args) -> tuple[int, dict]:
        r = self.run("ai-check", "--json", *args)
        return r.returncode, json.loads(r.stdout)


class Base(unittest.TestCase):
    git = True
    disable = ""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ai-template-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def copy(self, name="proj", git: bool | None = None, disable: str | None = None) -> Repo:
        dst = self.tmp / name
        shutil.copytree(TEMPLATE, dst, ignore=_ignore)
        use_git = self.git if git is None else git
        if use_git and HAS_GIT:
            subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
        dis = self.disable if disable is None else disable
        return Repo(dst, {"AI_TOOLS_DISABLE": dis} if dis else None)

    def initialized(self, **kw) -> Repo:
        repo = self.copy(**kw)
        repo.ok("ai-init", "--name", "Demo")
        return repo

    def new_task(self, repo: Repo, title="Add export", *extra) -> str:
        r = repo.ok("ai-task", "new", title, "--objective", "Users can export data",
                    "--accept", "Export endpoint returns CSV", "--validate", "python3 -m unittest",
                    "--class", "feature", *extra)
        return json.loads(r.stdout)["id"]


class TemplateTests(Base):
    def test_template_passes_check(self):
        code, out = self.copy().check()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["fail"], [])
        self.assertTrue(any("uninitialized template" in i for i in out["info"]))

    def test_template_ships_no_project_state(self):
        self.assertEqual(L.task_files(TEMPLATE), [])
        proj = L.load_json(TEMPLATE / ".ai/config/project.json")
        self.assertEqual(proj["instance"]["state"], "template")
        self.assertIsNone(L.load_json(TEMPLATE / ".ai/state/CURRENT_TASK.json")["task_id"])


class InitTests(Base):
    def test_greenfield_init(self):
        repo = self.initialized()
        proj = repo.json(".ai/config/project.json")
        self.assertEqual(proj["name"], "Demo")
        self.assertEqual(proj["instance"]["state"], "initialized")
        self.assertEqual(proj["instance"]["origin"], "greenfield")
        self.assertEqual(proj["objective"], "", "objective must never be invented")
        tasks = L.task_files(repo.root)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "queue")
        self.assertIsNone(repo.json(".ai/state/CURRENT_TASK.json")["task_id"])
        self.assertTrue((repo.root / ".ai/map/repo.json").is_file())
        self.assertNotIn("ai-project-template:readme", (repo.root / "README.md").read_text())
        self.assertEqual(repo.check()[0], 0)

    def test_rerun_init_is_safe(self):
        repo = self.initialized()
        watched = [".ai/config/project.json", ".ai/state/CURRENT_TASK.json", ".ai/state/ROADMAP.json",
                   ".ai/state/STATUS.md", "README.md"]
        before = {w: sha(repo.root / w) for w in watched}
        repo.ok("ai-init", "--name", "Other")
        self.assertEqual(before, {w: sha(repo.root / w) for w in watched})
        self.assertEqual(len(L.task_files(repo.root)), 1)

    def test_objective_only_when_given(self):
        repo = self.copy()
        repo.ok("ai-init", "--name", "Demo", "--objective", "A CLI that converts invoices")
        self.assertEqual(repo.json(".ai/config/project.json")["objective"], "A CLI that converts invoices")


class TaskTests(Base):
    def test_new_refuses_incomplete_task(self):
        repo = self.initialized()
        r = repo.run("ai-task", "new", "Only a title")
        self.assertEqual(r.returncode, 2)
        self.assertIn("refusing to create an incomplete task", r.stderr)

    def test_new_rejects_placeholders(self):
        repo = self.initialized()
        for bad in ("TODO", "TBD later", "<acceptance criterion>", "   "):
            r = repo.run("ai-task", "new", "Thing", "--objective", "Real objective", "--accept", bad,
                         "--validate", "make test", "--class", "feature")
            self.assertEqual(r.returncode, 2, bad)
        self.assertEqual(len(L.task_files(repo.root)), 1)

    def test_new_rejects_unknown_class(self):
        repo = self.initialized()
        r = repo.run("ai-task", "new", "Thing", "--objective", "Real objective", "--accept", "Works",
                     "--validate", "make test", "--class", "nonexistent")
        self.assertEqual(r.returncode, 2)

    def test_from_template_is_valid(self):
        repo = self.initialized()
        repo.ok("ai-task", "new", "--from-template", "project-discovery")
        self.assertEqual(repo.check()[0], 0)

    def test_state_machine(self):
        repo = self.initialized()
        tid = self.new_task(repo)
        r = repo.run("ai-task", "complete", tid, "--summary", "Done", "--evidence", "tests passed")
        self.assertEqual(r.returncode, 2, "queue→completed must be refused")
        self.assertIn("illegal transition", r.stderr)
        repo.ok("ai-task", "start", "T-0001")
        r = repo.run("ai-task", "start", tid)
        self.assertEqual(r.returncode, 2, "second active task must be refused")
        repo.ok("ai-task", "block", "T-0001", "--reason", "waiting for user")
        self.assertIsNone(repo.json(".ai/state/CURRENT_TASK.json")["task_id"])
        repo.ok("ai-task", "unblock", "T-0001", "--to", "active")
        repo.ok("ai-task", "complete", "T-0001", "--summary", "Discovery done", "--evidence", "ai-check exit 0")
        r = repo.run("ai-task", "start", "T-0001")
        self.assertEqual(r.returncode, 2, "completed→active must be refused")
        self.assertEqual(repo.check()[0], 0)

    def test_forced_transition_is_recorded(self):
        repo = self.initialized()
        repo.ok("ai-task", "complete", "T-0001", "--summary", "Skipped", "--evidence", "manual", "--force")
        task = json.loads(repo.ok("ai-task", "show", "T-0001").stdout)
        self.assertEqual(task["status"], "completed")
        self.assertTrue(task["history"][-1].get("forced"))
        self.assertEqual(repo.check()[0], 0)

    def test_dependencies_block_start(self):
        repo = self.initialized()
        tid = self.new_task(repo, "Later", "--dep", "T-0001")
        self.assertEqual(repo.run("ai-task", "start", tid).returncode, 2)

    def test_complete_writes_result_and_next_is_explicit(self):
        repo = self.initialized()
        tid = self.new_task(repo, "Follow-up", "--dep", "T-0001")
        repo.ok("ai-task", "start", "T-0001")
        out = json.loads(repo.ok("ai-task", "complete", "T-0001", "--summary", "Discovery done",
                                 "--evidence", "ai-check exit 0").stdout)
        self.assertIsNone(out["next"], "no next task without --next")
        self.assertIsNone(repo.json(".ai/state/CURRENT_TASK.json")["task_id"])
        self.assertTrue((repo.root / ".ai/context/summaries/T-0001.result.json").is_file())
        repo.ok("ai-task", "start", tid)
        repo.ok("ai-task", "complete", tid, "--summary", "Done", "--evidence", "tests pass", "--next")
        self.assertEqual(repo.check()[0], 0)

    def test_complete_next_follows_roadmap_then_id(self):
        repo = self.initialized()
        a = self.new_task(repo, "A")
        b = self.new_task(repo, "B")
        road = repo.json(".ai/state/ROADMAP.json")
        road["milestones"].append({"id": "M1", "title": "Next", "tasks": [b, a]})
        repo.write_json(".ai/state/ROADMAP.json", road)
        repo.ok("ai-task", "start", "T-0001")
        out = json.loads(repo.ok("ai-task", "complete", "T-0001", "--summary", "Done", "--evidence", "ok",
                                 "--next").stdout)
        self.assertEqual(out["next"], b)
        self.assertEqual(repo.json(".ai/state/CURRENT_TASK.json")["task_id"], b)


class PointerTests(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.initialized()
        self.repo.ok("ai-task", "start", "T-0001")
        self.cur = self.repo.json(".ai/state/CURRENT_TASK.json")

    def assertFails(self, needle):
        code, out = self.repo.check()
        self.assertEqual(code, 1)
        self.assertTrue(any(needle in f for f in out["fail"]), out["fail"])

    def test_valid_pointer(self):
        self.assertEqual(self.repo.check()[0], 0)

    def test_missing_task(self):
        self.repo.write_json(".ai/state/CURRENT_TASK.json", dict(self.cur, task_id="T-0099"))
        self.assertFails("missing task")

    def test_wrong_path(self):
        self.repo.write_json(".ai/state/CURRENT_TASK.json", dict(self.cur, path=".ai/tasks/queue/x.json"))
        self.assertFails("does not match")

    def test_completed_task(self):
        self.repo.ok("ai-task", "complete", "T-0001", "--summary", "Done", "--evidence", "ok")
        p = self.repo.json(".ai/state/CURRENT_TASK.json")
        self.repo.write_json(".ai/state/CURRENT_TASK.json",
                             dict(p, task_id="T-0001", path=L.task_files(self.repo.root)[0][1].relative_to(self.repo.root).as_posix()))
        self.assertFails("must be active")

    def test_status_directory_mismatch(self):
        _, path = L.task_files(self.repo.root)[0]
        d = json.loads(path.read_text())
        d["status"] = "queue"
        path.write_text(json.dumps(d))
        self.assertFails("does not match directory")


class MapTests(Base):
    def test_map_provenance(self):
        repo = self.initialized()
        meta = repo.json(".ai/map/repo.json")["meta"]
        for k in ("mapper_version", "generated_at", "root", "git_head", "dirty", "fingerprint", "method", "unavailable"):
            self.assertIn(k, meta)

    def test_missing_and_stale_map_warn(self):
        repo = self.initialized()
        (repo.root / ".ai/map/repo.json").unlink()
        code, out = repo.check()
        self.assertEqual(code, 0)
        self.assertTrue(any("map missing" in w for w in out["warn"]))
        repo.ok("ai-map")
        (repo.root / "src").mkdir()
        (repo.root / "src/new_module.py").write_text("x = 1\n")
        code, out = repo.check()
        self.assertEqual(code, 0)
        self.assertTrue(any("stale" in w for w in out["warn"]), out["warn"])

    def test_map_is_bounded_and_excludes_noise(self):
        repo = self.copy()
        (repo.root / "node_modules/pkg").mkdir(parents=True)
        (repo.root / "node_modules/pkg/index.js").write_text("x")
        (repo.root / "src").mkdir()
        for i in range(5):
            (repo.root / f"src/m{i}.py").write_text("x = 1\n")
        ctx = repo.json(".ai/config/context.json")
        ctx["map"]["max_files"] = 3
        repo.write_json(".ai/config/context.json", ctx)
        repo.ok("ai-map")
        m = repo.json(".ai/map/repo.json")
        self.assertTrue(m["meta"]["truncated"])
        self.assertLessEqual(m["summary"]["files"], 3)
        self.assertNotIn("JavaScript", m["summary"]["languages"])

    def test_map_does_not_count_protocol_tooling(self):
        repo = self.initialized()
        self.assertEqual(repo.json(".ai/config/project.json")["stack"]["languages"], [])


class RuntimeAndSecurityTests(Base):
    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_runtime_ignored_and_env_examples_tracked(self):
        repo = self.copy()
        def ignored(p):
            return subprocess.run(["git", "check-ignore", "-q", p], cwd=repo.root).returncode == 0
        self.assertTrue(ignored(".ai/runtime/available-models.json"))
        self.assertTrue(ignored(".ai/runtime/session.json"))
        self.assertFalse(ignored(".ai/runtime/.gitkeep"))
        self.assertTrue(ignored(".env"))
        self.assertTrue(ignored(".env.production.local"))
        self.assertFalse(ignored(".env.example"))
        self.assertFalse(ignored(".env.template"))
        self.assertFalse(ignored("docs/credentials-policy.md"))

    def test_runtime_problems_are_not_canonical_failures(self):
        repo = self.initialized()
        (repo.root / ".ai/runtime/available-models.json").write_text("{ not json")
        (repo.root / ".ai/runtime/usage.jsonl").write_text('{"usage_schema_version": 1}\n')
        code, out = repo.check()
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(out["runtime"]), 2)
        self.assertEqual(repo.check("--strict-runtime")[0], 1)
        r = repo.run("ai-route", "T-0001")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not valid JSON", r.stderr)

    def test_project_valid_without_runtime_dir(self):
        repo = self.initialized()
        shutil.rmtree(repo.root / ".ai/runtime")
        self.assertEqual(repo.check()[0], 0)
        repo.ok("ai-route", "T-0001")

    def test_secrets_in_runtime_are_not_canonical(self):
        repo = self.initialized()
        repo.write_json(".ai/runtime/provider-capabilities.json", {"api_key": "AKIA" + "ABCDEFGHIJKLMNOP"})
        self.assertEqual(repo.check()[0], 0)

    def test_secret_in_canonical_state_fails(self):
        repo = self.initialized()
        with open(repo.root / ".ai/knowledge/LESSONS.md", "a") as f:
            f.write("\nkey: AKIA" + "ABCDEFGHIJKLMNOP\n")
        code, out = repo.check()
        self.assertEqual(code, 1)
        self.assertTrue(any("possible secret" in x for x in out["fail"]))

    def test_path_traversal_refused(self):
        with self.assertRaises(ValueError):
            L.safe_path(TEMPLATE, "../outside.txt")
        repo = self.copy()
        proj = repo.json(".ai/config/project.json")
        proj["shims"].append("../outside.md")
        repo.write_json(".ai/config/project.json", proj)
        self.assertEqual(repo.check()[0], 1)


class RoutingTests(Base):
    REGISTRY = {"registry_schema_version": 1, "models": [
        {"id": "invented-9000", "provider": "nova-labs", "max_tier": 3, "reasoning_class": "deep",
         "cost_class": "medium", "latency_class": "normal", "context_class": "very_large",
         "capabilities": ["core.code_understanding", "core.tool_use", "core.filesystem", "core.reasoning",
                          "core.code_generation", "core.shell", "future.native_repo_reasoning"],
         "quantum_flux": {"unknown": "field preserved"}},
        {"id": "tiny", "provider": "local", "max_tier": 1, "reasoning_class": "basic", "cost_class": "free",
         "latency_class": "normal", "context_class": "small", "capabilities": ["core.summarization"]}]}

    def test_route_without_registry(self):
        repo = self.initialized()
        out = json.loads(repo.ok("ai-route", "T-0001").stdout)
        self.assertIn("requirements only", out["registry"])
        self.assertGreaterEqual(out["requirements"]["min_tier"], 1)

    def test_model_field_in_routing_is_rejected_by_schema(self):
        repo = self.copy()
        routing = repo.json(".ai/config/routing.json")
        routing["task_classes"]["feature"]["model"] = "some-model-name"
        repo.write_json(".ai/config/routing.json", routing)
        code, out = repo.check()
        self.assertEqual(code, 1)
        self.assertTrue(any("'model' is not allowed" in f or "model" in f for f in out["fail"]), out["fail"])

    def test_vendor_names_in_docs_are_fine(self):
        repo = self.copy()
        (repo.root / ".ai/knowledge/DECISIONS/0002-example.md").write_text("We benchmarked GPT, Claude and Gemini.\n")
        self.assertEqual(repo.check()[0], 0)

    def test_future_capability_preserved_and_matched(self):
        repo = self.initialized()
        cfg_before = {p.name: sha(p) for p in (repo.root / ".ai/config").glob("*.json")}
        tid = self.new_task(repo, "Repo-wide reasoning", "--cap", "future.native_repo_reasoning")
        task = json.loads(repo.ok("ai-task", "show", tid).stdout)
        self.assertIn("future.native_repo_reasoning", task["required_capabilities"])
        code, out = repo.check()
        self.assertEqual(code, 0)
        self.assertTrue(any("future.native_repo_reasoning" in i for i in out["info"]))
        repo.write_json(".ai/runtime/available-models.json", self.REGISTRY)
        self.assertEqual(repo.check("--strict-runtime")[0], 0, "unknown fields must be preserved, not rejected")
        route = json.loads(repo.ok("ai-route", tid).stdout)
        self.assertEqual([c["id"] for c in route["candidates"]], ["invented-9000"])
        self.assertEqual({p.name: sha(p) for p in (repo.root / ".ai/config").glob("*.json")}, cfg_before)

    def test_tier0_needs_no_model(self):
        repo = self.initialized()
        tid = json.loads(repo.ok("ai-task", "new", "Regenerate map", "--objective", "Refresh the repository map",
                                 "--accept", "repo.json is fresh", "--validate", "python3 tools/ai-check",
                                 "--class", "mechanical", "--risk", "low").stdout)["id"]
        out = json.loads(repo.ok("ai-route", tid).stdout)
        self.assertFalse(out["requirements"]["model_required"])


class ShimTests(Base):
    def test_shim_replaceable_without_touching_state(self):
        repo = self.initialized()
        state = [".ai/state/CURRENT_TASK.json", ".ai/state/ROADMAP.json", ".ai/state/STATUS.md"]
        before = {s: sha(repo.root / s) for s in state}
        (repo.root / "GEMINI.md").unlink()
        new = repo.root / ".github/copilot-instructions.md"
        new.parent.mkdir()
        new.write_text("Read AI_PROTOCOL.md, then .ai/config/project.json, then .ai/state/CURRENT_TASK.json.\n")
        proj = repo.json(".ai/config/project.json")
        proj["shims"] = ["AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"]
        repo.write_json(".ai/config/project.json", proj)
        self.assertEqual(repo.check()[0], 0)
        self.assertEqual(before, {s: sha(repo.root / s) for s in state})

    def test_shim_without_pointer_fails(self):
        repo = self.copy()
        (repo.root / "CLAUDE.md").write_text("# Project facts live here now\n")
        code, out = repo.check()
        self.assertEqual(code, 1)
        self.assertTrue(any("CLAUDE.md does not point" in f for f in out["fail"]))

    def test_large_shim_only_warns(self):
        repo = self.copy()
        with open(repo.root / "AGENTS.md", "a") as f:
            f.write("\n".join(f"- note {i}" for i in range(60)))
        code, out = repo.check()
        self.assertEqual(code, 0)
        self.assertTrue(any("AGENTS.md has" in w for w in out["warn"]))


class DegradationTests(Base):
    def test_without_git_ctags_jsonschema(self):
        repo = self.copy(git=False, disable="git,ctags,jsonschema,tomllib")
        repo.ok("ai-init", "--name", "NoTools")
        meta = repo.json(".ai/map/repo.json")["meta"]
        self.assertTrue(meta["method"].startswith("directory walk"))
        self.assertIsNone(meta["git_head"])
        self.assertTrue({"git", "ctags", "tomllib"} <= set(meta["unavailable"]))
        self.assertFalse((repo.root / ".ai/map/symbols.json").exists())
        code, out = repo.check()
        self.assertEqual(code, 0)
        self.assertTrue(out["validation_level"].startswith("baseline"))
        repo.ok("ai-task", "start", "T-0001")
        repo.ok("ai-route", "T-0001")

    def test_walk_respects_simple_gitignore(self):
        repo = self.copy(git=False, disable="git")
        (repo.root / "secret_build").mkdir()
        (repo.root / "secret_build/out.py").write_text("x=1\n")
        with open(repo.root / ".gitignore", "a") as f:
            f.write("secret_build/\n")
        repo.ok("ai-map")
        self.assertNotIn("secret_build", repo.json(".ai/map/repo.json")["code_dirs"])

    def test_baseline_reports_unsupported_keywords(self):
        os.environ["AI_TOOLS_DISABLE"] = "jsonschema"
        self.addCleanup(os.environ.pop, "AI_TOOLS_DISABLE", None)
        v = L.validate("abc", {"type": "string", "contentEncoding": "base64", "format": "email"})
        self.assertTrue(v.ok)
        self.assertEqual(v.unchecked, ["not checked: 'contentEncoding' at /"])
        self.assertTrue(v.level.startswith("baseline"))

    def test_shipped_schemas_use_only_supported_keywords(self):
        os.environ["AI_TOOLS_DISABLE"] = "jsonschema"
        self.addCleanup(os.environ.pop, "AI_TOOLS_DISABLE", None)
        repo = self.initialized(disable="jsonschema")
        code, out = repo.check()
        self.assertEqual(code, 0)
        self.assertFalse([w for w in out["warn"] if "not checked" in w])

    @unittest.skipUnless(L.jsonschema_module() is not None, "jsonschema not installed")
    def test_full_validation_agrees(self):
        repo = self.initialized(disable="")
        code, out = repo.check()
        self.assertEqual(code, 0, out)
        self.assertTrue(out["validation_level"].startswith("full"))


class InferenceTests(Base):
    """Regressions found by dogfooding on a real repository (pre-1.0.0 retrofit dry run)."""

    def make_layout(self, repo: Repo, backend: str = "hatchling.build") -> None:
        files = {
            "src/pkg/app.py": "x = 1\n", "src/pkg/cli.py": "x = 1\n",
            "scripts/run_job.py": "x = 1\n", "scripts/phase3_hypothesis_test.py": "x = 1\n",
            "tests/test_app.py": "def test_x(): pass\n", "tests/conftest.py": "\n",
            "test/legacy_check.py": "x = 1\n", "web/__tests__/a.test.js": "test('x', () => {})\n",
            "web/index.js": "export {}\n",
            "pyproject.toml": ('[build-system]\nrequires = ["hatchling"]\n'
                               f'build-backend = "{backend}"\n\n[project]\nname = "x"\n'),
        }
        for rel, text in files.items():
            (repo.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo.root / rel).write_text(text)

    def test_test_dirs_are_not_source_paths(self):
        repo = self.copy()
        self.make_layout(repo)
        repo.ok("ai-init", "--name", "Layout")
        paths = repo.json(".ai/config/project.json")["paths"]
        self.assertIn("src", paths["source"])
        self.assertIn("scripts", paths["source"], "a dir with real code stays source despite one *_test.py")
        self.assertIn("web", paths["source"])
        for t in ("tests", "test"):
            self.assertNotIn(t, paths["source"])
            self.assertIn(t, paths["tests"])
        self.assertIn("web/__tests__", paths["tests"])
        m = repo.json(".ai/map/repo.json")
        self.assertIn("tests", m["code_dirs"], "code_dirs still counts all code")
        self.assertNotIn("tests", m["source_dirs"])

    def test_build_backend_detected_with_and_without_tomllib(self):
        for disable in ("", "tomllib"):
            with self.subTest(disable=disable or "none"):
                repo = self.copy(name=f"bb-{disable or 'full'}", disable=disable)
                self.make_layout(repo)
                repo.ok("ai-init", "--name", "Backend")
                proj = repo.json(".ai/config/project.json")
                self.assertIn("hatchling", proj["stack"]["build_systems"])
                bb = repo.json(".ai/map/repo.json")["build_backends"]
                self.assertEqual(bb, [{"path": "pyproject.toml", "backend": "hatchling.build",
                                       "build_system": "hatchling", "source": "pyproject.toml [build-system]"}])
                self.assertEqual(repo.check()[0], 0)

    def test_unknown_build_backend_recorded_verbatim(self):
        repo = self.copy()
        self.make_layout(repo, backend="acme_builder.api")
        repo.ok("ai-map")
        self.assertIn("acme_builder.api", repo.json(".ai/map/repo.json")["build_systems"])

    def test_pyproject_without_build_system_infers_nothing(self):
        repo = self.copy()
        (repo.root / "pyproject.toml").write_text('[project]\nname = "x"\n[tool.other]\nbuild-backend = "nope"\n')
        repo.ok("ai-map")
        m = repo.json(".ai/map/repo.json")
        self.assertEqual(m["build_backends"], [])
        self.assertEqual(m["build_systems"], [])


class RetrofitTests(Base):
    def make_existing(self) -> Path:
        ex = self.tmp / "existing"
        (ex / "src").mkdir(parents=True)
        (ex / "src/app.py").write_text("print('hi')\n")
        (ex / "README.md").write_text("# Existing project\n")
        (ex / "AGENTS.md").write_text("# Our own agent notes\nUse tabs.\n")
        (ex / ".gitignore").write_text("dist/\n.env\n")
        (ex / "package.json").write_text(json.dumps({"name": "existing", "scripts": {"test": "vitest", "lint": "eslint ."}}))
        (ex / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
        if HAS_GIT:
            subprocess.run(["git", "init", "-q"], cwd=ex, check=True)
        return ex

    def test_retrofit_never_overwrites(self):
        tpl = self.copy("tpl", git=False)
        ex = self.make_existing()
        originals = {p: sha(ex / p) for p in ("src/app.py", "README.md", "AGENTS.md", "package.json")}
        old_gitignore = (ex / ".gitignore").read_text()
        r = Repo(ex).ok("ai-init", "--target", str(ex), tools_root=tpl.root)
        self.assertEqual(originals, {p: sha(ex / p) for p in originals})
        self.assertTrue((ex / ".gitignore").read_text().startswith(old_gitignore))
        self.assertIn(".ai/runtime/*", (ex / ".gitignore").read_text())
        self.assertIn("AGENTS.md", r.stdout)  # warned with snippet
        proj = json.loads((ex / ".ai/config/project.json").read_text())
        self.assertNotIn("AGENTS.md", proj["shims"])
        self.assertEqual(proj["instance"]["origin"], "retrofit")
        self.assertIn("pnpm", proj["stack"]["package_managers"])
        cmds = {c["cmd"]: c for c in proj["validation"]["commands"]}
        self.assertIn("pnpm run test", cmds)
        self.assertEqual(cmds["pnpm run test"]["source"], "package.json")
        self.assertFalse(cmds["pnpm run test"]["confirmed"])
        self.assertTrue((ex / "tools/ai-check").is_file())
        self.assertEqual(Repo(ex).check()[0], 0)
        # idempotent second run
        before = sha(ex / ".ai/config/project.json")
        Repo(ex).ok("ai-init", "--target", str(ex), tools_root=tpl.root)
        self.assertEqual(before, sha(ex / ".ai/config/project.json"))
        self.assertEqual(originals, {p: sha(ex / p) for p in originals})

    def test_retrofit_refuses_initialized_source(self):
        src = self.initialized()
        ex = self.make_existing()
        r = Repo(ex).run("ai-init", "--target", str(ex), tools_root=src.root)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((ex / ".ai").exists())


if __name__ == "__main__":
    unittest.main()
