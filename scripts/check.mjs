import { readdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
for (const dir of ['web','scripts','tests']) for (const file of readdirSync(dir)) {
  if (/\.(m?js)$/.test(file)) execFileSync(process.execPath,['--check',`${dir}/${file}`],{stdio:'inherit'});
}
execFileSync('python3',['-m','compileall','-q','simulator','scripts','tests'],{stdio:'inherit',env:{...process.env,PYTHONPYCACHEPREFIX:'.runtime/pycache'}});
