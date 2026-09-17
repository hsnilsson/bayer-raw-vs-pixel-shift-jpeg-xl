const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('scripts/generate_break_even_report_site.py', 'utf8').replace(/\r\n/g, '\n');
const calls = [];
const c = {workspaceActive: true, document: {}, state: {overlay:false, modeKey:'normal'}, Event: class {constructor(type) {this.type=type;}}};
function select(options) {
  const label = {dataset:{}};
  return {options, selectedIndex:0, get value() {return this.options[this.selectedIndex];},
    closest: () => label, matches: selector => selector === 'select',
    focus() {c.document.activeElement=this;}, dispatchEvent(event) {calls.push(event.type);}};
}
c.referenceSelect = select(['raw61','ps16']);
c.modeSelect = select(['normal','shadow','negative']);
c.filmSidebar = {dataset:{}}; c.qualitySidebar = {dataset:{}};
const button = {matches:()=>false, focus() {c.document.activeElement=this;}};
c.filmList = c.qualityList = {querySelector:()=>button};
c.workspace = {contains:control => [button,c.referenceSelect,c.modeSelect].includes(control)};
c.pinWorkspaceViewport = () => {};
c.moveViewer = delta => calls.push(['film',delta]);
c.moveCandidate = delta => calls.push(['quality',delta]);
c.setOverlay = enabled => {c.state.overlay=enabled;};
c.currentViewer = () => ({metadata:{viewModes:c.modeSelect.options.map(key=>({key}))}});
c.setMode = key => {c.state.modeKey=key;c.modeSelect.selectedIndex=c.modeSelect.options.indexOf(key);};
vm.createContext(c);
vm.runInContext(source.match(/const navigationZones = .*;/)[0]+'\nlet activeNavigationZone="film";',c);
for (const name of ['setNavigationZone','moveNavigationZone','moveReference','moveMode']) {
  const start = source.indexOf('    function '+name+'(');
  assert(start >= 0, name);
  vm.runInContext(source.slice(start,source.indexOf('\n    }',start)+6),c);
}
const start=source.indexOf('    document.addEventListener("keydown", (event) => {');
const body=source.slice(start,source.indexOf('\n    });',start)+8);
let handler;c.document.addEventListener=(name,fn)=>{handler=fn;};vm.runInContext(body,c);
function press(key,extra={}) {
  let prevented=false;
  handler({key,target:c.document.activeElement,preventDefault(){prevented=true;},...extra});
  return prevented;
}
function zone() {return vm.runInContext('activeNavigationZone',c);}
c.setNavigationZone('film',true);
for (const expected of ['reference','view','quality']) {
  const before=[c.referenceSelect.value,c.modeSelect.value];
  assert.equal(press('ArrowRight'),true);assert.equal(zone(),expected);
  assert.deepEqual([c.referenceSelect.value,c.modeSelect.value],before);
}
assert.equal(press('ArrowRight'),true);assert.equal(zone(),'quality');
for (const expected of ['view','reference','film']) {assert(press('ArrowLeft'));assert.equal(zone(),expected);}
assert(press('ArrowLeft'));assert.equal(zone(),'film');
for (const [name,control] of [['reference',c.referenceSelect],['view',c.modeSelect]]) {
  c.setNavigationZone(name,true);
  assert(press('ArrowDown'));assert.equal(control.selectedIndex,1);
  assert(press('ArrowUp'));assert.equal(control.selectedIndex,0);
  assert(press('ArrowUp'));assert.equal(control.selectedIndex,0);
  const before=control.value, overlay=c.state.overlay;
  assert(press('o'));assert.equal(c.state.overlay,!overlay);assert.equal(control.value,before);
  assert(press('O'));assert.equal(c.state.overlay,overlay);
  assert.equal(press('ArrowRight',{ctrlKey:true}),false);assert.equal(zone(),name);
}
c.document.activeElement={matches:selector=>selector.includes('input')};
assert.equal(press('o'),false);
c.workspaceActive=false;c.document.activeElement=null;
assert.equal(press('ArrowRight'),false);
console.log('Four-column navigation, bounded dropdown selection, overlay shortcuts and editable-field guards passed.');
