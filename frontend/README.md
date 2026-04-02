# Frontend - Vue 3 + PrimeVue + Tailwind CSS

Moderní frontend postavený na Vue 3, Vite, PrimeVue a Tailwind CSS.

## Prerekvizity

- Node.js (doporučená verze 20+)
- npm

## Instalace a spuštění

Před prvním spuštěním nebo při změně závislostí nainstalujte balíčky:

```powershell
# Přepněte se do složky frontendu
cd src/frontend

# Nainstalujte závislosti
npm install
```

### Vývojový režim
Spustí lokální server s Hot Module Replacement (HMR):

```powershell
npm run dev
```
Výchozí adresa: `http://localhost:5173`

### Produkční sestavení
Vytvoří optimalizovaný build v adresáři `dist/`:

```powershell
npm run build
```

### Preview buildu
Lokální náhled produkčního sestavení:

```powershell
npm run preview
```

## Použitý Stack

- **Vue 3** (Composition API)
- **Vite** - Build tool
- **TypeScript** - Statické typování
- **PrimeVue v4** - Komponentová knihovna (Theme: Aura)
- **Tailwind CSS v4** - Utility-first CSS framework
- **Pinia** - State management
- **Vue Router** - Routing
- **PrimeIcons** - Sada ikon
