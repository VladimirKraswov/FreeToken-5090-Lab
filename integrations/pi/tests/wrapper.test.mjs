import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,copyFileSync,writeFileSync,readFileSync,rmSync,chmodSync} from 'node:fs';
import {join} from 'node:path';import {tmpdir,homedir} from 'node:os';import {spawnSync} from 'node:child_process';
for(const status of [0,7,130])test(`wrapper starts one process, preserves exit status ${status}`,t=>{
 const dir=mkdtempSync(join(tmpdir(),'pi-wrapper-'));t.after(()=>rmSync(dir,{recursive:true,force:true}));
 mkdirSync(join(dir,'bin'));mkdirSync(join(dir,'.pi'));writeFileSync(join(dir,'.pi/AUTONOMOUS'),'legacy opt-in');
 copyFileSync(new URL('../bin/pi-local-autonomous',import.meta.url),join(dir,'bin/pi-local-autonomous'));
 writeFileSync(join(dir,'bin/pi-local'),'#!/bin/zsh\nprint -r -- "called" >> "$CALLS"\nexit "$TEST_STATUS"\n');chmodSync(join(dir,'bin/pi-local'),0o755);
 const result=spawnSync('zsh',[join(dir,'bin/pi-local-autonomous')],{cwd:dir,env:{...process.env,CALLS:join(dir,'calls'),TEST_STATUS:String(status)},timeout:1500,encoding:'utf8'});
 assert.equal(result.error,undefined);assert.equal(result.status,status);assert.equal(readFileSync(join(dir,'calls'),'utf8'),'called\n');
});
