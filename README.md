# Hydrawise HomeKit System 0.2.0

Parallel-Testintegration für `hydrawise_local_pro`.

Sie läuft zusätzlich zur bisherigen `hydrawise_homekit_pro` und verwendet standardmäßig Port 21065.

## HomeKit-Modell

Ein einzelnes HomeKit-Accessory:

- `IrrigationSystem` als Primary Service
- alle Hydrawise-Zonen als verknüpfte `Valve`-Services
- `ValveType = Irrigation`
- `SetDuration`
- `RemainingDuration`
- `ServiceLabelIndex`

Queue-Zustände:

- Aus: Active=0, InUse=0
- Wartet: Active=1, InUse=0
- Läuft: Active=1, InUse=1

Die Gesamtanlage meldet `InUse=1`, wenn irgendeine Zone tatsächlich läuft.
`RemainingDuration` der Anlage summiert laufende und wartende Zonen.

## Installation

Ordner `custom_components/hydrawise_homekit_system` nach `/config/custom_components/` kopieren,
Home Assistant neu starten und danach `Hydrawise HomeKit System` als Integration hinzufügen.

Standardport: 21065

Diese Integration ist bewusst ein Paralleltest. Die bestehende v0.1 muss dafür nicht gelöscht werden.

## Wichtig

Vor dem Pairing sollte das gleiche Zonenset nicht gleichzeitig über mehrere Bridges produktiv verwendet werden.
Zum Testen kann die neue System-Bridge separat gekoppelt und danach verglichen werden.
