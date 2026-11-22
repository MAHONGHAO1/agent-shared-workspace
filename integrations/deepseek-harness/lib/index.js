import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

export const name = 'agent-shared-workspace';
export const PACKAGE_NAME = 'dsh-agent-shared-workspace';

export function resolveSharedWorkspaceSkillRoot(profileBaseUrl) {
  if (!profileBaseUrl) {
    throw new Error('dsh-agent-shared-workspace: missing DSH profile baseUrl for package resolution');
  }
  let manifestPath;
  try {
    manifestPath = createRequire(profileBaseUrl).resolve(`${PACKAGE_NAME}/package.json`);
  } catch (error) {
    throw new Error(
      `dsh-agent-shared-workspace: cannot resolve ${PACKAGE_NAME}/package.json from the DSH profile`,
      { cause: error },
    );
  }
  return join(dirname(manifestPath), 'skills');
}
