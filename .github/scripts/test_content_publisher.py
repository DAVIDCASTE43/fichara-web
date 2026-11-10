import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name('content_publisher.py')
SCRATCH = Path(os.environ.get('TMPDIR') or tempfile.gettempdir())


def sample(slug='prueba-organizacion'):
    return {'slug': slug, 'title': 'Una guía útil para el taller', 'description': 'Una propuesta práctica de organización, sin obligaciones inventadas.', 'category': 'Organización', 'status': 'ready', 'intro': ['Consejos de organización para una empresa pequeña.'], 'sections': [{'heading': 'Lista de comprobación', 'paragraphs': ['Un ejemplo ficticio, no un caso de cliente.'], 'bullets': ['Revisar los datos.']}], 'sources': [{'title': 'Funciones', 'url': 'https://fichara.com/#funciones'}], 'related': [], 'worksheet': {'filename': 'lista.csv', 'rows': [['Tarea', 'Estado'], ['Comprobar', 'Pendiente']]}}


class PublisherTests(unittest.TestCase):
    def load(self):
        self.assertTrue(MODULE.is_file(), 'Falta el publicador de contenido')
        spec = importlib.util.spec_from_file_location('content_publisher', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def make_repo(self, root, articles):
        (root / '.github').mkdir()
        (root / 'blog').mkdir()
        (root / 'blog/index.html').write_text('<html><div class="blog-grid">ANTERIORES</div></html>', encoding='utf-8')
        (root / 'sitemap.xml').write_text('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://fichara.com/</loc></url><url><loc>https://fichara.com/blog/</loc><lastmod>2026-01-01</lastmod></url></urlset>', encoding='utf-8')
        (root / 'llms.txt').write_text('# FichaRA\n', encoding='utf-8')
        (root / '.github/content-queue.json').write_text(json.dumps({'version': 1, 'articles': articles}), encoding='utf-8')

    def test_dry_run_does_not_write_any_file(self):
        publisher = self.load()
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            self.make_repo(root, [sample()])
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = publisher.run(root, '2026-11-10', apply=False)
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(before, after)


    def test_apply_publishes_one_article_and_updates_discovery_once(self):
        publisher = self.load()
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            self.make_repo(root, [sample(), sample('segunda-guia')])
            result = publisher.run(root, '2026-11-10', apply=True)
            self.assertEqual(result['status'], 'published_to_repository')
            html = (root / 'blog/prueba-organizacion/index.html').read_text(encoding='utf-8')
            self.assertIn('2026-11-10', html)
            self.assertEqual(html.count('<h1>'), 1)
            self.assertTrue((root / 'blog/prueba-organizacion/lista.csv').exists())
            self.assertFalse((root / 'blog/segunda-guia').exists())
            url = 'https://fichara.com/blog/prueba-organizacion/'
            self.assertEqual((root / 'blog/index.html').read_text(encoding='utf-8').count(url), 1)
            self.assertEqual((root / 'sitemap.xml').read_text(encoding='utf-8').count(url), 1)
            self.assertIn('<loc>https://fichara.com/blog/</loc><lastmod>2026-11-10</lastmod>', (root / 'sitemap.xml').read_text(encoding='utf-8'))
            queue = json.loads((root / '.github/content-queue.json').read_text(encoding='utf-8'))
            self.assertEqual(queue['articles'][0]['status'], 'published')
            receipts = json.loads((root / '.github/content-published.json').read_text(encoding='utf-8'))
            self.assertEqual(receipts['articles'][0]['url'], url)
            repeated = publisher.run(root, '2026-11-10', apply=True)
            self.assertEqual(repeated['status'], 'already_ran_today')

    def test_existing_url_blocks_without_overwriting(self):
        publisher = self.load()
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            self.make_repo(root, [sample()])
            target = root / 'blog/prueba-organizacion/index.html'
            target.parent.mkdir()
            target.write_text('existing article', encoding='utf-8')
            with self.assertRaises(ValueError):
                publisher.run(root, '2026-11-10', apply=True)
            self.assertEqual(target.read_text(encoding='utf-8'), 'existing article')

    def test_invalid_slugs_and_duplicate_slugs_are_rejected(self):
        publisher = self.load()
        for articles in [[sample('../outside')], [sample(), sample()]]:
            with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
                root = Path(directory)
                self.make_repo(root, articles)
                with self.assertRaises(ValueError):
                    publisher.run(root, '2026-11-10', apply=True)
                self.assertFalse((root / '.github/content-published.json').exists())

    def test_unready_or_exhausted_queue_changes_nothing(self):
        publisher = self.load()
        for status in ['draft', 'needs_review', 'published']:
            with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
                root = Path(directory)
                article = sample()
                article['status'] = status
                self.make_repo(root, [article])
                result = publisher.run(root, '2026-11-10', apply=True)
                self.assertEqual(result['status'], 'empty')
                self.assertFalse((root / 'blog/prueba-organizacion').exists())

    def test_bad_index_fails_before_writing_article(self):
        publisher = self.load()
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            self.make_repo(root, [sample()])
            (root / 'blog/index.html').write_text('new incompatible design', encoding='utf-8')
            with self.assertRaises(ValueError):
                publisher.run(root, '2026-11-10', apply=True)
            self.assertFalse((root / 'blog/prueba-organizacion').exists())

    def test_html_is_escaped_and_csv_formulas_are_neutralized(self):
        publisher = self.load()
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            article = sample()
            article['title'] = '<script>alert(1)</script>'
            article['worksheet']['rows'].append(['=IMPORTXML("example")', '@command'])
            self.make_repo(root, [article])
            publisher.run(root, '2026-11-10', apply=True)
            html = (root / 'blog/prueba-organizacion/index.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>alert(1)</script>', html)
            self.assertIn('&lt;script&gt;', html)
            csv_text = (root / 'blog/prueba-organizacion/lista.csv').read_text(encoding='utf-8-sig')
            self.assertIn("'=IMPORTXML", csv_text)
            self.assertIn("'@command", csv_text)

    def test_external_links_are_rejected(self):
        publisher = self.load()
        with self.assertRaises(ValueError):
            publisher.safe_url('javascript:alert(1)')
        with self.assertRaises(ValueError):
            publisher.safe_url('https://example.org/untrusted')

if __name__ == '__main__':
    unittest.main()
