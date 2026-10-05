// Exercise the shipped rendering functions with a minimal DOM, no npm packages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(0, 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new vm.Script(script); // Check the whole UI, including handlers outside this test.
class Element {
  constructor() { this.children=[]; this.style={}; this.textContent=''; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); }
  replaceChildren(...items) { this.children=items; }
}
const hosts = Object.fromEntries(['overview-device-cards','overview-battery-cards','summary-device-count'].map(id=>[id,new Element()]));
const context = vm.createContext({
  document: {getElementById:id=>hosts[id], createElement:()=>new Element()},
  l:values=>values.en,
  batteryState: {keep_battery_position:false, devices:[{
    device_id:'0PVPTEST', manual:{2:'SERIAL_B'}, automatic:{2:'SERIAL_A'},
    detected:[{serial:'SERIAL_A',physical_slot:2},{serial:'SERIAL_B',physical_slot:3}]
  }], inventory:[{device_id:'0PVPTEST', family:'noah', display_name:'NOAH', wifi_signal_strength:-62,
    batteries:[{slot:1,soc:0},{slot:2,serial:'SERIAL_B',soc:80},{slot:3,serial:'SERIAL_A',soc:null}]}]}
});
vm.runInContext(script.slice(script.indexOf('function renderOverviewDevices()'), script.indexOf('async function loadOverviewLogs()')),context);
for (const value of [null,undefined,'',NaN]) assert.equal(context.clampSoc(value),null);
assert.equal(context.clampSoc(0),0);
assert.equal(context.clampSoc(120),100);
context.renderOverviewDevices();
assert.equal(hosts['overview-device-cards'].children[0].children[2].children[1].textContent,'-62 dBm');
for (const value of [null,0,10,-121,'invalid']) {
  context.batteryState.inventory[0].wifi_signal_strength=value;
  context.renderOverviewDevices();
  assert.equal(hosts['overview-device-cards'].children[0].children[2].children[1].textContent,'–');
}
context.renderOverviewBatteries();
const cards=hosts['overview-battery-cards'].children;
assert.equal(cards.length,3);
assert.equal(cards[0].children[2].textContent,'0%');
assert.equal(cards[1].children[1].children[1].textContent,'SERIAL_B');
assert.equal(cards[1].children[1].children[2].textContent,'Manually assigned');
assert.equal(cards[2].children[1].children[1].textContent,'SERIAL_A');
assert.equal(cards[2].children[2].textContent,'–');
assert.equal(cards[2].children[0].children[0].style.height,'0%');
assert.ok(!html.includes('data-go-tab='));
console.log('Ingress rendering checks passed');
