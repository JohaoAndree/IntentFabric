# ADR-00X: [Título corto que describe la decisión]

- Estado: Proposed | Accepted (aprobado el DD-MM-AAAA) | Superseded por ADR-0YY
- Etapa: E_
- Depende de: ADR-___
- Referencias: (opcional) papers, documentación oficial o literatura que respalde la decisión.
- Walkthrough: docs/walkthroughs/ADR-00X.md

---
## PARTE A — DECISIÓN (congelada al aceptar)

### 1. Contexto
Problema y restricciones del proyecto que afectan la decisión (laboratorio, tiempo, perfil, alcance).

### 2. Alternativas
Al menos dos, viables y descritas completas, con fuente cuando exista.
1. **[Alternativa 1]**: descripción, ventajas, desventajas.
2. **[Alternativa 2]**: descripción, ventajas, desventajas.

### 3. Criterios de elección
Factores específicos de este proyecto (no genéricos), cada uno con su efecto en el sistema.

### 4. Decisión
Alternativa elegida, en una o dos líneas.

### 5. Sustento
Justificación explícita contra los criterios del punto 3.

### 6. Consecuencias y riesgos aceptados
Qué se pierde o se complica, y cómo se mitiga (máximo 3-4 líneas).

---
## PARTE B — ESPECIFICACIÓN DE IMPLEMENTACIÓN (para el agente)

### 7. Alcance y fuera de alcance
- Incluye: …
- NO incluye: …

### 8. Pasos de implementación
Lista ordenada por punto de control (commit): archivos exactos a crear o tocar, interfaces o firmas públicas, reglas y la verificación local del paso.
1. **[Paso 1 — título corto]**:
   - Archivos: `ruta/archivo`
   - Cambios / Firmas: …
   - Verificación del paso: `[comando o prueba que debe pasar antes del commit]`

### 9. Criterios de aceptación
Lista verificable, con las pruebas requeridas.

### 10. Registro de cambios de la Parte B
| Fecha | Archivos afectados | Cambio / Implementación | Resultado / Validación | Motivo |
|---|---|---|---|---|
| DD-MM-AAAA | `ruta/archivos` | Descripción concisa del cambio realizado | Estado de las pruebas / validación | Justificación del cambio |