"""Run study code with archive-local tools and explicit workspace write boundaries.

Usage: <archive>/tooling/python/python.exe -I -S -B run.py rendered scripts/check_verified_release.py
Modes: rendered, controlled, muimg, public-exact. Arguments after the script are passed unchanged.
"""
import builtins, importlib, json, os, runpy, shutil, subprocess, sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
WORK=REPO/'work/study'
CONFIG=json.loads((WORK/'restore.json').read_text(encoding='utf-8'))['paths']
ARCHIVE=Path(CONFIG['archive']);SCRATCH=Path(CONFIG['scratch'])

def norm(p):return os.path.normcase(str(Path(p).resolve()))
ALLOWED=(norm(ARCHIVE),norm(REPO),norm(WORK),norm(SCRATCH))
def inside(p,roots):
    if isinstance(p,(int,type(None))):return True
    value=norm(p)
    return value==norm(os.devnull) or any(value==r or value.startswith(r+os.sep) for r in roots)
def assert_write(path):
    if isinstance(path,(int,type(None))):return
    if inside(path,(norm(ARCHIVE),norm(REPO/'archive'))) or not inside(path,(norm(REPO),norm(WORK),norm(SCRATCH))):
        raise PermissionError('Study write outside mutable workspace: '+str(path))

def audit(event,args):
    if event=='open':
        path,mode,flags=args
        if not inside(path,ALLOWED):raise PermissionError('Restore read outside archive/workspace: '+str(path))
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)):
            assert_write(path)
    if event in ('os.listdir','os.scandir') and not inside(args[0],ALLOWED):
        raise PermissionError('Restore directory read outside archive/workspace: '+str(args[0]))
    if event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.utime'):
        assert_write(args[0])
    if event in ('os.rename','os.replace'):
        assert_write(args[0]);assert_write(args[1])
    if event=='subprocess.Popen':
        executable,argv,cwd,env=args
        for arg in argv if isinstance(argv,(list,tuple)) else [argv]:
            text=str(arg);candidate=text.split('=',1)[-1]
            if len(candidate)>2 and candidate[1]==':' and candidate[2] in '/\\' and not inside(candidate,ALLOWED):
                raise PermissionError('Native argument outside archive/workspace: '+candidate)

def configure(mode):
    os.chdir(REPO)
    settings=WORK/'runtime-settings/rawtherapee'
    preserved=ARCHIVE/'tooling/rawtherapee-user-settings'
    if not settings.exists() and preserved.exists():
        shutil.copytree(preserved,settings)
        options=settings/'options'
        replacements={'StartupDirectory':'home','StartupPath':str(REPO),
            'LoadSaveProfilePath':str(settings/'profiles'),'LastICCProfCreatorDir':str(settings/'profiles'),
            'PathFolder':str(WORK/'scratch'),'LastSaveAsPath':str(WORK/'scratch'),
            'ICCDirectory':str(ARCHIVE/'tooling/system-color-profiles')}
        lines=[]
        for line in options.read_text(encoding='utf-8-sig').splitlines():
            k=line.split('=',1)[0]
            lines.append(k+'='+replacements[k].replace('\\','\\\\') if k in replacements else line)
        options.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    os.environ['RT_SETTINGS']=str(settings)
    os.environ['RT_CACHE']=str(WORK/'runtime-settings/rawtherapee-cache')
    os.environ['LC_ALL']='C'
    for name in ('PYTHONHOME','PYTHONPATH'):os.environ.pop(name,None)
    for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
    tmp=WORK/'tmp';tmp.mkdir(exist_ok=True);os.environ['TEMP']=os.environ['TMP']=str(tmp)
    os.environ['PATH']=os.pathsep.join([str(REPO/'archive/tooling-extra/node'),str(ARCHIVE/'tooling/libjxl/bin'),str(ARCHIVE/'tooling/exiftool'),str(ARCHIVE/'tooling/rawtherapee'),os.environ.get('SystemRoot','C:/Windows')+'/System32'])
    package_mode='rendered' if mode=='public-exact' else mode
    packages={'rendered':[ARCHIVE/'tooling/rendered-packages',ARCHIVE/'tooling/python/Lib/site-packages'],
              'controlled':[ARCHIVE/'tooling/python/Lib/site-packages',ARCHIVE/'tooling/controlled-packages'],
              'muimg':[ARCHIVE/'tooling/muimg/venv/Lib/site-packages']}[package_mode]
    sys.path[:0]=[str(REPO/'src'),str(REPO/'scripts'),*[str(p) for p in packages]]
    sys.dont_write_bytecode=True
    sys.addaudithook(audit)

def preserve_public_icc():
    # Only the packaging-time sRGB profile is supplied from the report-bound bytes.
    # The frozen scientific script still creates fresh pixels and encodes them.
    import hashlib,io
    from PIL import ImageCms
    evidence=json.loads((REPO/'site/data/public-evidence.json').read_text(encoding='utf-8'))
    gray=[(i,r) for i,r in enumerate(evidence['records']) if len(r['source_shape'])==2]
    assert len(gray)==1
    index,record=gray[0]
    path=ARCHIVE/'payload/D/CodexTemp/jpegxl-vs-dngpixelshift/verified-report-rebuild/public'/str(index)/'source.icc'
    data=path.read_bytes();assert hashlib.sha256(data).hexdigest()==record['working_profile']['icc_sha256']
    profile=ImageCms.ImageCmsProfile(io.BytesIO(data))
    assert ImageCms.ImageCmsProfile(profile.profile).tobytes()==data
    original=ImageCms.createProfile
    def retained(colorSpace,colorTemp=-1):
        if colorSpace=='sRGB':return profile.profile
        return original(colorSpace,colorTemp)
    ImageCms.createProfile=retained
    print('Using retained public sRGB ICC:',hashlib.sha256(data).hexdigest(),flush=True)

def runtime_check():
    modules=('numpy','PIL','tifffile','imagecodecs') if sys.argv[1]=='rendered' else ('numpy','rawpy') if sys.argv[1]=='controlled' else ('muimg','numpy','tifffile','imagecodecs','click')
    result={'python':sys.version,'executable':sys.executable,'mode':sys.argv[1],'modules':{}}
    for name in modules:
        m=importlib.import_module(name)
        assert inside(m.__file__,(norm(ARCHIVE),)),m.__file__
        result['modules'][name]={'version':getattr(m,'__version__',None),'path':m.__file__}
    if sys.argv[1]=='controlled':
        import numpy,rawpy
        assert numpy.__version__=='2.3.5' and rawpy.__version__=='0.27.1'
        result['libraw']=rawpy.libraw_version
    elif sys.argv[1]=='rendered':
        import numpy
        assert numpy.__version__=='2.5.3'
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    if len(sys.argv)<3:raise SystemExit(__doc__)
    mode,script=sys.argv[1:3];configure(mode)
    if script=='--runtime-check':runtime_check()
    elif script=='--tests':
        import unittest
        unittest.main(module=None,argv=['unittest','discover','-s',str(REPO/'tests'),'-v'])
    else:
        target=(REPO/script).resolve()
        if not target.is_relative_to(REPO) or target.is_relative_to(ARCHIVE):raise ValueError('Script must belong to editable project')
        if mode=='public-exact':
            if script!='scripts/rebuild_public_evidence.py':raise ValueError('public-exact only applies to the public evidence stage')
            preserve_public_icc()
        sys.argv=[str(target),*sys.argv[3:]];runpy.run_path(str(target),run_name='__main__')
