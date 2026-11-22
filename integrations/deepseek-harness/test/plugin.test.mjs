import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { name, PACKAGE_NAME, resolveSharedWorkspaceSkillRoot } from '../lib/index.js';

const pkgRoot = dirname(dirname(fileURLToPath(import.meta.url)));

test('package metadata and cordis patch are aligned', () => {
  const pkg = JSON.parse(readFileSync(join(pkgRoot, 'package.json'), 'utf8'));
  assert.equal(pkg.name, PACKAGE_NAME);
  assert.equal(name, 'agent-shared-workspace');
  assert.equal(pkg.dsh?.bundle?.patch, './cordis.patch.yml');

  const patch = readFileSync(join(pkgRoot, 'cordis.patch.yml'), 'utf8');
  assert.match(patch, /@deepseek-ai\/dsh-skill-filesystem/);
  assert.match(patch, /dsh-agent-shared-workspace\/package\.json/);
});

test('bundled shared-workspace skill and CLI script exist', () => {
  const skillMd = join(pkgRoot, 'skills', 'shared-workspace', 'SKILL.md');
  const toolPy = join(pkgRoot, 'skills', 'shared-workspace', 'scripts', 'workspace_tool.py');
  assert.equal(existsSync(skillMd), true);
  assert.equal(existsSync(toolPy), true);

  const md = readFileSync(skillMd, 'utf8');
  assert.match(md, /^---\r?\nname:\s*shared-workspace/m);
});

test('resolveSharedWorkspaceSkillRoot throws on missing baseUrl', () => {
  assert.throws(() => resolveSharedWorkspaceSkillRoot(''), /missing DSH profile baseUrl/);
});
