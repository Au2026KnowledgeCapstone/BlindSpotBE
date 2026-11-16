import re
import unittest

from backend.main import app


class OpenApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.get('/openapi.json') as response:
            self.assertEqual(response.status_code, 200)
            self.spec = response.get_json()

    def test_swagger_ui_uses_local_spec(self):
        for path in ('/docs', '/docs/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'/openapi.json', response.data)
            self.assertIn(b'SwaggerUIBundle', response.data)

    def test_spec_covers_every_application_operation_and_current_response(self):
        expected = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint in {'static', 'openapi_spec', 'swagger_ui'}:
                continue
            path = re.sub(r'<([^>]+)>', r'{\1}', rule.rule)
            path = path.replace('{project_name}', '{project_id}')
            actual_path = re.sub(r'<([^>]+)>', lambda m: 'example-' + m[1], rule.rule)
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                expected.add((path, method.lower()))
                operation = self.spec['paths'][path][method.lower()]
                response = self.client.open(actual_path, method=method, json={})
                documented = operation['responses'][str(response.status_code)]
                example = documented['content']['application/json']['example'].copy()
                # Echo endpoints reflect whatever body the caller submits.
                if 'data_received' in example:
                    example['data_received'] = {}
                self.assertEqual(example, response.json, (path, method))
                parameters = {p['name'] for p in operation['parameters'] if p['in'] == 'path'}
                self.assertEqual(parameters, set(re.findall(r'{([^}]+)}', path)))
        documented = {(path, method) for path, operations in self.spec['paths'].items()
                      for method in operations}
        self.assertEqual(expected, documented)
        ids = [op['operationId'] for ops in self.spec['paths'].values() for op in ops.values()]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == '__main__':
    unittest.main()
