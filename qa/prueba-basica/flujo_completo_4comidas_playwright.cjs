const { ejecutar } = require('./soporte_playwright.cjs');
ejecutar({ completo: true }).catch(error => { console.error(error.message); process.exitCode = 1; });
