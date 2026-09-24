-- dbo.ListaInternados source (definición original tal cual la devuelve OBJECT_DEFINITION)

CREATE VIEW [dbo].[ListaInternados] AS
    SELECT
        h.HCL_CODIGO                                   AS [NRO HISTORIA],
        LTRIM(RTRIM(h.HCL_NOMBRE))                     AS [NOMBRE],
        LTRIM(RTRIM(h.HCL_APPAT))                      AS [PATERNO],
        LTRIM(RTRIM(h.HCL_APMAT))                      AS [MATERNO],
        LTRIM(RTRIM(h.HCL_SEXO))                       AS [SEXO],             

        s.VGRUCODIGO                                   AS [CODIGO SERVICIO CAMA],
        LTRIM(RTRIM(v.VGRUDESCRI))                     AS [SERVICIO_OFICIAL], 
        s.SA_CODIGO                                    AS [SA_CODIGO],       
        LTRIM(RTRIM(s.SA_ENUM))                        AS [PIEZA],            
        LTRIM(RTRIM(s.SA_DESCRIPCION))                 AS [SALA_SIGLA],      
        c.CAM_CODIGO                                   AS [CAM_CODIGO],      
        LTRIM(RTRIM(c.CAM_ENUM))                       AS [CAMA],        

        o.ORAT_CODIGO                                  AS [ORAT_CODIGO],      
        d.VGRUCODIGO                                   AS [CODIGO SERVICIO INTERNACION],
        LTRIM(RTRIM(v1.VGRUDESCRI))                    AS [SERVICIO_INTERNACION]

    FROM SE_ORATENCAB o
    INNER JOIN SE_ORATENDET d  ON d.ORAT_CODIGO = o.ORAT_CODIGO
    INNER JOIN SE_CAMA      c  ON c.CAM_CODIGO  = d.CAM_CODIGO
    INNER JOIN SE_SALA      s  ON s.SA_CODIGO   = c.SA_CODIGO
    INNER JOIN SE_HC        h  ON h.HCL_CODIGO  = o.HCL_CODIGO
    LEFT  JOIN VGRUPOSI     v  ON v.VGRUCODIGO  = s.VGRUCODIGO   
    LEFT  JOIN VGRUPOSI    v1  ON v1.VGRUCODIGO = d.VGRUCODIGO
    WHERE d.ORATDET_EST = 'V';
