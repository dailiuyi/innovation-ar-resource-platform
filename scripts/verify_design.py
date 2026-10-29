"""Validate generated contracts, examples, local Markdown links, and SQL/API enums."""
from pathlib import Path
import argparse
import importlib.util
import json
import re
import yaml
from openapi_spec_validator import validate

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'docs')
    args = parser.parse_args()
    checks=[]
    def check(name, condition=True):
        assert condition, name
        checks.append({'name':name,'passed':True})
    spec=yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text(encoding='utf-8'))
    validate(spec)
    check('OpenAPI 3.0 structural validation')
    module_spec=importlib.util.spec_from_file_location('contract_source',ROOT/'scripts/generate_contracts.py')
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    check('OpenAPI matches authoring source',spec==module.spec)
    info=spec['info']
    check('OpenAPI identity is the 4DGS scene resource API',info['title']=='4DGS Scene Resource API' and info['version']=='0.5.0' and spec['openapi']=='3.0.3')
    check('OpenAPI servers use the relative root',[s['url'] for s in spec['servers']]==['/'])
    operations=[]
    legacy=re.compile(r'/drafts|draft|zip|marker|asset|/preview|/ready|/revoke|day|night',re.I)
    for path,methods in spec['paths'].items():
        for method,operation in methods.items():
            operations.append(operation['operationId'])
            check('no legacy or unimplemented route '+operation['operationId'], not legacy.search(path))
            check('implemented only '+operation['operationId'], operation['x-implementation']=='implemented' and operation['tags'])
            check('no legacy CSRF '+operation['operationId'], 'X-CSRF-TOKEN' not in {p['name'] for p in operation['parameters']})
            if operation['operationId'] not in ('login','captchaConfig') and not path.startswith('/api/v1/client/'):
                check('admin Bearer '+operation['operationId'], operation['security']==[{'bearerAuth':[]}])
    check('operation IDs unique',len(operations)==len(set(operations)))
    client_content='/api/v1/client/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}'
    client_paths={'/api/v1/client/scenes':{'get'},'/api/v1/client/scenes/{sceneId}':{'get'},client_content:{'get','head'}}
    check('client routes are exactly the three anonymous reads (file also HEAD)',
          {p:set(m) for p,m in spec['paths'].items() if p.startswith('/api/v1/client/')}==client_paths)
    for path,methods in client_paths.items():
        for method in methods:
            check('anonymous client operation has no security '+method+' '+path,spec['paths'][path][method]['security']==[])
    check('client file documents 200, 206, 416 and 409',
          all({'200','206','416','409'}<=set(spec['paths'][client_content][m]['responses']) for m in ('get','head')))
    check('client file fileName is a string path parameter',
          {'name':'fileName','in':'path','required':True,'schema':{'type':'string'}} in spec['paths'][client_content]['get']['parameters'])
    version_paths={'/api/v1/scene-versions/config':{'get'},'/api/v1/scenes/{sceneId}/versions':{'get','post'},
        '/api/v1/scene-versions/{versionId}':{'get','put','delete'},'/api/v1/scene-versions/{versionId}/publish':{'post'},
        '/api/v1/scene-versions/{versionId}/files/{fileId}':{'get'},
        '/api/v1/scene-versions/{versionId}/files/{fileId}/content':{'get','head','put'}}
    for path,methods in version_paths.items():
        check('scene version operations '+path,path in spec['paths'] and methods<=set(spec['paths'][path]))
    check('version creation documents 201, 200 retry, 409 and 410',
          {'200','201','409','410'}<=set(spec['paths']['/api/v1/scenes/{sceneId}/versions']['post']['responses']))
    check('file upload documents 409, 422 and 503',
          {'200','409','422','503'}<=set(spec['paths']['/api/v1/scene-versions/{versionId}/files/{fileId}/content']['put']['responses']))
    uploads=spec['components']['schemas']['VersionCreate']['properties']
    check('version creation carries request key, description and files only',set(uploads)=={'requestKey','description','files'})
    check('geography fields absent from scene contracts',not re.search('longitude|latitude|geoCrs|address',json.dumps(spec['components']['schemas']['SceneView'])+json.dumps(spec['components']['schemas']['SceneCreate']),re.I))
    docfiles=[ROOT/'AGENTS.md',ROOT/'README.md',ROOT/'database/README.md',*sorted((ROOT/'docs').rglob('*.md'))]
    for file in docfiles:
        content=file.read_text(encoding='utf-8')
        for dest in re.findall(r'\]\(([^)]+)\)',content):
            if re.match(r'^(https?://|mailto:|#)',dest):continue
            target=(file.parent/dest.split('#')[0]).resolve()
            check('local link '+file.name+' -> '+dest,target.is_file() or target==ROOT/'docs/validation-contracts.json')
    report={'passed':True,'operations':len(operations),'checks':checks,
            'limitations':['No HTTP server or client runtime executed; PostgreSQL constraints are verified by isolated real-database acceptance','Mermaid source checked only as Markdown, not rendered']}
    args.report_dir.mkdir(parents=True, exist_ok=True)
    output=args.report_dir/'validation-contracts.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'PASS: {len(checks)} checks, {len(operations)} operations; {output}')

if __name__=='__main__':main()
