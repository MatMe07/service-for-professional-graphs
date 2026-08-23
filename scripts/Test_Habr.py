import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from graph_service.learning.parsers.habr import HabrProvider

def main():
    node_name = "Python Developer"
    if not node_name:
        print("Ошибка: название не может быть пустым")
        return

    parser = HabrProvider()
    results = parser.search(node_name, limit=1)
    print(results)
    # print(f"\nНайдено {len(results)} статей по запросу «{node_name}»:\n")
    # for i, item in enumerate(results, 1):
    #     print(f"{i}. {item['title']}")
    #     print(f"   URL: {item['url']}")
    #     print(f"   Язык: {item['language']}")
    #     print()

if __name__ == "__main__":
    main()
