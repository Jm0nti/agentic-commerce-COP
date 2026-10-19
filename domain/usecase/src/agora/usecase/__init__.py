"""`domain/usecase` del scaffold de Bancolombia: un caso de uso por carpeta,
`<caso>/<caso>_use_case.py`, con la clase terminada en `UseCase`.

Solo depende de `domain/model`. `usecase/agente/` vive aca porque orquestar el turno
es logica de aplicacion, pero con una regla mas estricta que la del resto
(`tests/arquitectura/test_fronteras.py`): no puede importar ningun otro caso de uso.
"""
