"""Protect the inward-facing package graph established by the architecture refactor."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "knowledge"

ALLOWED_PACKAGE_DEPENDENCIES = {
    "command_interfaces": {
        "document_processing",
        "experiments",
        "knowledge_base",
        "knowledge_domain",
        "model_integration",
        "revision_store",
        "runtime_support",
        "source_workflows",
        "system_maintenance",
    },
    "document_processing": {"knowledge_domain", "revision_store", "runtime_support"},
    "experiments": {
        "knowledge_domain",
        "literature",
        "model_integration",
        "runtime_support",
        "source_workflows",
    },
    "knowledge_base": {"document_processing", "knowledge_domain", "revision_store"},
    "knowledge_domain": set(),
    "literature": {"knowledge_domain"},
    "model_integration": {"knowledge_domain", "runtime_support"},
    "revision_store": {"knowledge_domain"},
    "runtime_support": set(),
    "source_workflows": {
        "document_processing",
        "knowledge_base",
        "knowledge_domain",
        "literature",
        "model_integration",
        "revision_store",
        "runtime_support",
    },
    "system_maintenance": {
        "document_processing",
        "knowledge_domain",
        "literature",
        "revision_store",
        "runtime_support",
    },
    "web_interface": {
        "document_processing",
        "experiments",
        "knowledge_base",
        "knowledge_domain",
        "literature",
        "model_integration",
        "revision_store",
        "runtime_support",
    },
}

PURE_PROPOSAL_MODULES = {
    "knowledge.source_workflows.article_claim_extraction",
    "knowledge.source_workflows.claim_matching",
    "knowledge.source_workflows.note_revision_proposals",
}
FORBIDDEN_PROPOSAL_DEPENDENCIES = {
    "knowledge.knowledge_base",
    "knowledge.literature.zotero_client",
    "knowledge.revision_store",
    "knowledge.source_workflows.claim_reconciliation",
    "knowledge.source_workflows.note_consolidation",
    "knowledge.source_workflows.source_import",
}


def source_modules() -> dict[str, Path]:
    return {
        ".".join(path.with_suffix("").relative_to(SOURCE_ROOT.parent).parts): path
        for path in SOURCE_ROOT.rglob("*.py")
    }


def internal_imports(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    imports = []
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("knowledge")
        ):
            imports.append((node.module, tuple(alias.name for alias in node.names)))
        elif isinstance(node, ast.Import):
            imports.extend(
                (alias.name, ()) for alias in node.names if alias.name.startswith("knowledge")
            )
    return imports


def module_dependencies(
    module: str,
    path: Path,
    modules: dict[str, Path],
) -> set[str]:
    dependencies = set()
    for imported, names in internal_imports(path):
        if imported in modules:
            dependencies.add(imported)
        dependencies.update(
            candidate for name in names if (candidate := f"{imported}.{name}") in modules
        )
    dependencies.discard(module)
    return dependencies


def test_packages_only_depend_inward() -> None:
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCE_ROOT)
        if len(relative.parts) < 2:
            continue
        package = relative.parts[0]
        for imported, _ in internal_imports(path):
            parts = imported.split(".")
            if len(parts) < 2 or parts[1] == package:
                continue
            if parts[1] not in ALLOWED_PACKAGE_DEPENDENCIES[package]:
                violations.append(f"{relative}: {package} -> {parts[1]}")
    assert not violations, "Outward package dependencies:\n" + "\n".join(violations)


def test_internal_module_graph_is_acyclic() -> None:
    modules = source_modules()
    dependencies = {
        module: module_dependencies(module, path, modules) for module, path in modules.items()
    }
    visited = set()
    active = []

    def visit(module: str) -> None:
        if module in active:
            cycle = " -> ".join([*active[active.index(module) :], module])
            raise AssertionError(f"Internal import cycle: {cycle}")
        if module in visited:
            return
        active.append(module)
        for dependency in dependencies[module]:
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in modules:
        visit(module)


def test_proposal_modules_do_not_import_acceptance_or_storage() -> None:
    modules = source_modules()
    dependencies = {
        module: module_dependencies(module, modules[module], modules)
        for module in PURE_PROPOSAL_MODULES
    }
    violations = {
        module: sorted(
            dependency
            for dependency in imported
            if any(
                dependency == forbidden or dependency.startswith(forbidden + ".")
                for forbidden in FORBIDDEN_PROPOSAL_DEPENDENCIES
            )
        )
        for module, imported in dependencies.items()
    }
    violations = {module: imported for module, imported in violations.items() if imported}
    assert not violations, f"Proposal modules crossed acceptance boundaries: {violations}"
