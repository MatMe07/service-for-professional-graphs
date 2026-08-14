from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def validate_graph(graph: dict[str, Any], min_children: int = 3) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if len(graph) != 1:
        issues.append(ValidationIssue("error", "$", "В графе должен быть ровно один корень профессии."))
        return issues
    root_name, root_value = next(iter(graph.items()))
    if not isinstance(root_value, dict) or not root_value:
        issues.append(ValidationIssue("error", root_name, "Корень графа не должен быть пустым."))
        return issues
    _walk(root_value, [root_name], min_children, issues)
    return issues


def _walk(node: dict[str, Any], path: list[str], min_children: int, issues: list[ValidationIssue]) -> None:
    if "count" in node:
        if set(node) != {"count"} or not isinstance(node["count"], int) or not 1 <= node["count"] <= 100:
            issues.append(ValidationIssue("error", " > ".join(path), "Лист должен иметь только целочисленный count от 1 до 100."))
        return
    if len(node) < min_children:
        issues.append(
            ValidationIssue(
                "error",
                " > ".join(path),
                f"У ветки {len(node)} дочерних нод; целевое правило требует минимум {min_children}.",
            )
        )
    for name, child in node.items():
        if name in path:
            issues.append(ValidationIssue("error", " > ".join([*path, name]), "Обнаружено самовложение."))
            continue
        if not isinstance(child, dict):
            issues.append(ValidationIssue("error", " > ".join([*path, name]), "Значение ноды должно быть объектом."))
            continue
        _walk(child, [*path, name], min_children, issues)


def collect_leaf_names(graph: dict[str, Any]) -> set[str]:
    names: set[str] = set()

    def visit(node: dict[str, Any]) -> None:
        for name, child in node.items():
            if isinstance(child, dict) and set(child) == {"count"}:
                names.add(name)
            elif isinstance(child, dict):
                visit(child)

    for root in graph.values():
        if isinstance(root, dict):
            visit(root)
    return names


def validate_product_layers(
    graphs: dict[str, dict[str, Any]],
    image_dictionary: dict[str, Any],
    course_dictionary: dict[str, Any],
    image_root: Path,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    all_nodes: set[str] = set()
    for graph in graphs.values():
        all_nodes.update(collect_leaf_names(graph))
    image_nodes = image_dictionary.get("nodes", {})
    for name in sorted(all_nodes):
        if name not in image_nodes:
            issues.append(ValidationIssue("error", name, "Нода отсутствует в image_dictionary.json."))
        else:
            image = image_nodes[name].get("image", "")
            image_path = (image_root / image).resolve() if image else image_root
            if image and not image_path.is_relative_to(image_root.resolve()):
                issues.append(ValidationIssue("error", name, "Путь SVG выходит за пределы папки изображений."))
            elif not image or not image_path.is_file():
                issues.append(ValidationIssue("error", name, "SVG-файл не найден."))
            else:
                issues.extend(_validate_svg(name, image_path))
        if name not in course_dictionary:
            issues.append(ValidationIssue("error", name, "Нода отсутствует в course_dictionary.json."))
        elif not isinstance(course_dictionary[name], list):
            issues.append(ValidationIssue("error", name, "Учебные материалы должны быть списком URL."))
        elif not course_dictionary[name]:
            issues.append(ValidationIssue("warning", name, "Список учебных материалов пока пуст."))
    return issues


def _validate_svg(node_name: str, path: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as exc:
        return [ValidationIssue("error", node_name, f"Некорректный SVG XML: {exc}")]
    if root.tag.rsplit("}", 1)[-1] != "svg":
        issues.append(ValidationIssue("error", node_name, "Корневой элемент изображения должен быть svg."))
    if root.attrib.get("viewBox") != "0 0 800 480":
        issues.append(ValidationIssue("error", node_name, "SVG должен иметь viewBox 0 0 800 480."))
    forbidden = {"script", "foreignObject", "iframe", "image"}
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name in forbidden:
            issues.append(ValidationIssue("error", node_name, f"Запрещённый SVG-элемент: {local_name}."))
        for attribute, value in element.attrib.items():
            local_attribute = attribute.rsplit("}", 1)[-1]
            if local_attribute in {"href", "src"} and not str(value).startswith("#"):
                issues.append(ValidationIssue("error", node_name, "Внешние ссылки в SVG запрещены."))
            if local_attribute.lower().startswith("on"):
                issues.append(ValidationIssue("error", node_name, "Обработчики событий в SVG запрещены."))
    return issues
