"""Validate generated contracts, examples, local Markdown links, and SQL/API enums."""
from pathlib import Path
import argparse
import copy
import importlib.util
import json
import re
import yaml
from jsonschema import Draft202012Validator, FormatChecker
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
    check('OpenAPI identity is the 4DGS scene resource API',info['title']=='4DGS Scene Resource API' and info['version']=='0.4.0' and spec['openapi']=='3.0.3')
    check('OpenAPI servers use the relative root',[s['url'] for s in spec['servers']]==['/'])
    descriptor_schema=json.loads((ROOT/'contracts/schemas/resource-descriptor.schema.json').read_text(encoding='utf-8'))
    descriptor=json.loads((ROOT/'contracts/examples/resource-descriptor.json').read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(descriptor_schema)
    descriptor_validator=Draft202012Validator(descriptor_schema,format_checker=FormatChecker())
    descriptor_validator.validate(descriptor)
    check('resource descriptor Draft 2020-12 schema and example')
    check('resource descriptor schema matches authoring source',descriptor_schema==module.resource_descriptor_schema())
    check('resource descriptor example matches authoring source',descriptor==module.resource_descriptor_example())
    variant_ids=[v['id'] for v in descriptor['variants']]
    check('resource descriptor variant IDs unique and default exists',len(variant_ids)==len(set(variant_ids)) and descriptor['defaultVariant'] in variant_ids)
    for v in descriptor['variants']:
        ends=[s['startSeconds']+s['durationSeconds'] for s in v['segments']]
        starts=[s['startSeconds'] for s in v['segments']]
        check('resource descriptor segments ordered without overlap '+v['id'],all(starts[i+1]>=ends[i] for i in range(len(starts)-1)))
    for name, mutate in [
       ('missing settings',lambda x:x.pop('settings')),
       ('unknown descriptor field',lambda x:x.update(address='x')),
       ('empty variants',lambda x:x.update(variants=[])),
       ('invalid variant ID',lambda x:x['variants'][0].update(id='Bad Id')),
       ('unsupported format version',lambda x:x.update(formatVersion=2)),
       ('zero segment duration',lambda x:x['variants'][0]['segments'][0].update(durationSeconds=0)),
       ('negative segment start',lambda x:x['variants'][0]['segments'][0].update(startSeconds=-1)),
       ('two-element scale',lambda x:x['transform'].update(scale=[1,1]))]:
        changed=copy.deepcopy(descriptor);mutate(changed)
        check('reject descriptor '+name,bool(list(descriptor_validator.iter_errors(changed))))
    operations=[]
    legacy=re.compile(r'/drafts|draft|zip|marker|asset|/client/|/preview|/ready|/revoke|day|night',re.I)
    for path,methods in spec['paths'].items():
        for method,operation in methods.items():
            operations.append(operation['operationId'])
            check('no legacy or unimplemented route '+operation['operationId'], not legacy.search(path))
            check('implemented only '+operation['operationId'], operation['x-implementation']=='implemented' and operation['tags'])
            check('no legacy CSRF '+operation['operationId'], 'X-CSRF-TOKEN' not in {p['name'] for p in operation['parameters']})
            if operation['operationId'] not in ('login','captchaConfig'):
                check('admin Bearer '+operation['operationId'], operation['security']==[{'bearerAuth':[]}])
    check('operation IDs unique',len(operations)==len(set(operations)))
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
    component=spec['components']['schemas']['ResourceDescriptor']
    check('OpenAPI descriptor is the OpenAPI 3.0 subset of resource.json v1',component==module.openapi_schema(module.resource_descriptor_schema()) | {'description':component['description']}
          and '$schema' not in component and '$id' not in component)
    duration=component['properties']['variants']['items']['properties']['segments']['items']['properties']['durationSeconds']
    check('OpenAPI segment duration is positive without 2020-12 exclusiveMinimum',duration=={'type':'number','minimum':0,'not':{'enum':[0]}})
    uploads=spec['components']['schemas']['VersionCreate']['properties']
    check('version creation carries request key, descriptor and files',set(uploads)=={'requestKey','description','descriptor','files'})
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
