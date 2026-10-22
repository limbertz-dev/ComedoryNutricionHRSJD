/** Exportadores reales y SQL fixture. No usa cuentas, MySQL ni la API del laboratorio. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const raiz = fileURLToPath(new URL('../../', import.meta.url));
const carpetaQa = path.join(raiz, 'qa/prueba-basica');
const require = createRequire(new URL('../../comedorfront/package.json', import.meta.url));
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href);
const ExcelJS = require('exceljs');
const { navegador } = createRequire(import.meta.url)('./soporte_playwright.cjs');
const carpeta = path.join(carpetaQa, 'evidencias', `reportes-offline-${new Date().toISOString().replace(/[:.]/g, '-')}`);
const python = path.join(raiz, 'comedorback/.venv/Scripts/python.exe');
const generado = spawnSync(python, ['-B',path.join(carpetaQa,'reportes_historicos_offline.py'),'--salida',carpeta],
  { cwd: raiz, encoding:'utf8', env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'} });
assert.equal(generado.status,0,generado.stderr);
const datos = JSON.parse(await fs.readFile(path.join(carpeta,'datos.json'),'utf8'));
const server = await createServer({ root:path.join(raiz,'comedorfront'),configFile:false,envFile:false,
  server:{host:'127.0.0.1',port:0,open:false},
  optimizeDeps:{include:['jspdf','jspdf-autotable','exceljs/dist/exceljs.min.js']} });
server.middlewares.use((req,res,next)=>{
  if(req.url!=='/prueba-offline'){next();return;}
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end('<!doctype html><html lang="es"><title>Prueba offline de reportes</title><body><h1>Exportaciones de prueba</h1></body></html>');
});
await server.listen();
const browser = await navegador().launch({headless:true});
const contexto = await browser.newContext({acceptDownloads:true,viewport:{width:1366,height:768}});
const page = await contexto.newPage();
page.setDefaultTimeout(45000);
const pruebas=[];
const textos={};
const matrices={};
try {
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/prueba-offline`);
  await page.evaluate(async fixtures=>{
    window.fixtures=fixtures;
    window.api=await import('/src/api.js');
    window.exportadores=await import('/src/exportaciones.js');
    const original=window.fetch;
    window.fetch=async (url,opciones)=>{
      const u=new URL(url);
      if(!u.pathname.startsWith('/reportes/'))return original(url,opciones);
      const nombre=u.pathname.endsWith('/registro-diario')?'diario':u.pathname.endsWith('/mensual')?'mensual':u.pathname.endsWith('/gestion')?'gestion':u.searchParams.get('hasta')==='2026-10-31'?'mixto':'rango';
      return new Response(JSON.stringify(window.fixtures[window.fase][nombre]),{status:200,headers:{'Content-Type':'application/json'}});
    };
  },datos);
  let precargado=false;
  for(const fase of ['antes','ambos_inactivos'])for(const nombre of ['diario','mensual','gestion','rango','mixto']){
    const informe = await page.evaluate(async ({fase,nombre})=>{
      window.fase=fase;
      const argumentos={gestion:2026,mesIndice:8,hoy:new Date('2026-10-20T12:00:00')};
      window.informe=nombre==='diario'?await window.api.obtenerRegistroDiario(argumentos)
        :nombre==='mensual'?await window.api.obtenerInformeMensual(argumentos)
          :nombre==='gestion'?await window.api.obtenerResumenGestion(argumentos)
            :await window.api.obtenerInformeRaciones({...argumentos,desde:'2026-09-01',hasta:nombre==='mixto'?'2026-10-31':'2026-09-30'});
      window.informe.archivo=`${fase}-${nombre}`;
      return window.informe;
    },{fase,nombre});
    for(const extension of ['pdf','xlsx']){
      const descarga=page.waitForEvent('download');
      await page.evaluate(extension=>extension==='pdf'?window.exportadores.exportarInformePdf(window.informe):window.exportadores.exportarInformeExcel(window.informe),extension);
      const archivo=await descarga;
      assert.equal(archivo.suggestedFilename(),`${fase}-${nombre}.${extension}`);
      await archivo.saveAs(path.join(carpeta,archivo.suggestedFilename()));
    }
    // Desde aqui el navegador pierde completamente la conexion. Los exportadores ya estan cargados.
    if(!precargado){await contexto.setOffline(true);precargado=true;}
    const libro=new ExcelJS.Workbook();
    await libro.xlsx.readFile(path.join(carpeta,`${fase}-${nombre}.xlsx`));
    // Una sola hoja, como el PDF: tabla, coeficientes y cierre juntos.
    assert.equal(libro.worksheets.length,1,'El Excel debe traer una sola hoja.');
    const hoja=libro.getWorksheet('Informe');
    assert.ok(hoja,'Falta la hoja Informe del Excel.');
    let total;
    const matriz=[];
    hoja.eachRow(row=>{matriz.push(row.values.slice(1));if(row.getCell(1).value==='TOTAL')total=row;});
    assert.ok(total,'Falta la fila TOTAL del Excel.');
    const numero=cell=>cell.value!==null&&typeof cell.value==='object'?cell.value.result:cell.value;
    const columnas=informe.encabezados.length;
    assert.equal(numero(total.getCell(columnas)),informe.totalGeneral);
    informe.totalesPorCategoria.forEach((n,i)=>assert.equal(numero(total.getCell(i+2)),n));
    // Mismas posiciones que columnasDeCierre() de exportaciones.js.
    const servidas=Math.max(2,columnas-5);
    const [cServ,cCoef,cEquiv]=[servidas,servidas+1,servidas+3];
    (informe.grupos??[]).forEach(grupo=>{
      let fila;
      hoja.eachRow(row=>{if(row.getCell(1).value===`${grupo.etiqueta.toUpperCase()} :`)fila=row;});
      assert.ok(fila,`Falta el coeficiente de ${grupo.etiqueta} en el Excel.`);
      assert.equal(numero(fila.getCell(cServ)),grupo.servidas);
      assert.equal(numero(fila.getCell(cEquiv)),grupo.equivalente);
      if(grupo.coeficienteVariable){
        assert.equal(fila.getCell(cCoef).value,'Variable');
        assert.equal(typeof fila.getCell(cEquiv).value,'number','El equivalente mixto no debe recalcularse con un coeficiente unico.');
      }else assert.equal(Math.round(grupo.servidas*fila.getCell(cCoef).value*100)/100,numero(fila.getCell(cEquiv)));
    });
    const extraido=spawnSync('pdftotext',['-raw',path.join(carpeta,`${fase}-${nombre}.pdf`),'-'],{encoding:'utf8'});
    assert.equal(extraido.status,0,'Se requiere pdftotext para verificar el PDF generado.');
    assert.ok(/total/i.test(extraido.stdout));
    const esperados=[...informe.totalesPorCategoria,informe.totalGeneral].join(' ');
    assert.ok(extraido.stdout.split('\n').some(linea=>{
      const texto=linea.trim().replace(/\s+/g,' ');
      return texto===esperados || texto.replace(/^total\s+/i,'')===esperados;
    }),`El PDF ${nombre} no contiene la fila de totales esperada.`);
    if(nombre==='mixto')assert.ok(extraido.stdout.includes('Variable'));
    const clave=`${fase}-${nombre}`;
    textos[clave]=extraido.stdout;
    matrices[clave]=matriz;
    if(fase==='ambos_inactivos'){
      assert.equal(textos[clave],textos[`antes-${nombre}`],'El contenido del PDF cambio al desactivar catalogos.');
      assert.deepEqual(matrices[clave],matrices[`antes-${nombre}`],'Las cifras o formulas del Excel cambiaron.');
    }
    pruebas.push({fase,informe:nombre,total:informe.totalGeneral,equivalente:informe.totalEquivalente??null,pdf:'PASA',excel:'PASA'});
    console.log(`PASA ${fase}/${nombre}: ${informe.totalGeneral} raciones; PDF y Excel conciliados.`);
  }
  const escapar=valor=>String(valor).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const etiquetas={diario:'Registro diario',mensual:'Informe mensual',gestion:'Resumen anual',rango:'Rango de septiembre',mixto:'Rango con coeficientes variables'};
  const filas=pruebas.map(p=>`<tr><td>${p.fase==='antes'?'Catálogo activo':'Categoría y Almuerzo inactivos'}</td><td>${etiquetas[p.informe]}</td><td>${p.total}</td><td>${p.equivalente??'—'}</td><td><a href="${p.fase}-${p.informe}.pdf">PDF</a> · <a href="${p.fase}-${p.informe}.xlsx">Excel</a></td></tr>`).join('');
  const html=`<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Reportes históricos — prueba offline</title><style>body{font:16px system-ui;color:#12233d;background:#f3faf6;max-width:1050px;margin:32px auto;padding:24px}h1{color:#00663f}table{width:100%;border-collapse:collapse;background:white}th,td{text-align:left;padding:12px;border:1px solid #cfd8d5}th{background:#effbf5}a{color:#00663f}p{line-height:1.6}code{overflow-wrap:anywhere}</style><h1>Reportes históricos: comprobación offline</h1><p><strong>APROBADO.</strong> Datos sintéticos sobre SQLite real en memoria. No requiere MySQL, cuentas ni conexión para abrir este documento, los PDF o Excel guardados.</p><p>Se conservaron cifras y clasificación tras desactivar una categoría y Almuerzo. Se comprobaron cuatro formatos de informe y un rango con coeficientes variables. Los rechazos no forman parte de las raciones servidas.</p><table><thead><tr><th>Estado del catálogo</th><th>Informe</th><th>Raciones</th><th>Equivalente</th><th>Archivos offline</th></tr></thead><tbody>${filas}</tbody></table><p>Los archivos son copias fijas de esta ejecución. <a href="datos.json">Datos y comparación completa</a> · <a href="sha256.json">Huellas de integridad</a>.</p><p>La integridad de las copias se comprueba con <code>python qa/prueba-basica/reportes_historicos_offline.py --verificar "${escapar(carpeta)}"</code>. Editar un archivo hace fallar esa comprobación.</p></html>`;
  await fs.writeFile(path.join(carpeta,'index.html'),html);
  await page.goto(new URL(`file:///${carpeta.replaceAll('\\','/')}/index.html`).href);
  assert.equal(await page.locator('tbody tr').count(),10);
  await page.screenshot({path:path.join(carpeta,'reporte-offline.png'),fullPage:true});
  await fs.writeFile(path.join(carpeta,'resultado.json'),JSON.stringify({aprobado:true,navegador_sin_conexion:true,pruebas},null,2));
  const hashes={};
  for(const archivo of await fs.readdir(carpeta))hashes[archivo]=createHash('sha256').update(await fs.readFile(path.join(carpeta,archivo))).digest('hex');
  await fs.writeFile(path.join(carpeta,'sha256.json'),JSON.stringify(hashes,null,2));
  const integridad=spawnSync(python,['-B',path.join(carpetaQa,'reportes_historicos_offline.py'),'--verificar',carpeta],{encoding:'utf8'});
  assert.equal(integridad.status,0,integridad.stderr);
  console.log(integridad.stdout.trim());
  console.log(`APROBADO. Abrir sin conexion: ${path.join(carpeta,'index.html')}`);
}finally{
  await browser.close();await server.close();
}
