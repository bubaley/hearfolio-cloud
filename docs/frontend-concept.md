# Frontend concept

How to add and grow a feature. Folder roles: [architecture.md](architecture.md). Full working example: `frontend/app/features/organization/` (`user` for tokens/nested lists, `/ui` for primitives).

A feature is `frontend/app/features/<name>/` with `resources/` (API descriptors) and `views/`. Add `components/` and `composables/` as soon as a view would otherwise mix unrelated UI or logic.

Pages stay thin. Views get API data only through a **resource descriptor** and the templates or `shared/api` composables built on it (Pinia Colada queries and mutations over the generated client) — never `useFetch`/`$fetch` for API resources. The current organization is `useSetupStore().state.organization`; every request sends its `Organization-Key`.

---

## Data layer

```
openapi.json ──pnpm gen:api──► shared/api/generated/   types + SDK functions (organizationsList, …) + fetch client
                                      │
plugins/api.ts ── $api (one client per app instance: cookies, Organization-Key, 401 refresh)
                                      │
features/<name>/resources/<entity>.ts ── defineResource({ key, sdk, toForm, toCreate, toUpdate })
                                      │
shared/api/useResource.ts ── useResourceList / useResourceItem / useResourceMutations (Pinia Colada)
                                      │
AppListTemplate / AppDetailTemplate / AppSelect :resource="organizationResource"
```

### Generated client

`frontend/openapi.json` is written by `make openapi` from the backend; `pnpm gen:api` (`openapi-ts.config.ts`, `@hey-api/openapi-ts` pinned) turns it into `app/shared/api/generated/`: request/response types named after the backend schemas (`OrganizationReadSchema`, `OrganizationCreateSchema`, …) and one function per operationId (`organizations_list` → `organizationsList`). `make gen-client` runs both. Never edit generated files; commit them with the schema. `pnpm gen:api:check` (part of `pnpm check`) fails when they are stale. The folder is excluded from Oxlint, knip and the architecture guard but typechecked.

The client flavor is `@hey-api/client-fetch` (native fetch, also on the Nitro server). Operation paths already contain `/api/v1`, so the base URL is only the origin:

| Where | Base URL | Credentials |
|---|---|---|
| Browser | `''` — same origin: Caddy in the image, the `nuxt dev` proxy (`modules/dev-proxy.ts`) in development | HttpOnly cookies set by FastAPI; a 401 runs `POST /auth/refresh` once (single flight for concurrent requests) and replays the request; a failed refresh clears the session and sends app routes to `/auth?redirect=…` |
| SSR | `NUXT_API_INTERNAL_URL` (server-only runtime config) | The incoming `cookie` header is forwarded; no refresh: a 401 renders signed out. SSR only issues GETs (the CSRF Origin check rejects cookie-authenticated unsafe requests without `Origin`) |

`plugins/api.ts` creates the client per Nuxt app instance — never share one client between SSR requests — and provides it as `$api`; `useApiClient()` returns it. Failed requests reject with `ApiError` (`status`, `code`, `details` from the `ErrorResponse` envelope); check them with `isApiError(error, 401)`. Calling an SDK function directly (actions that are not CRUD, e.g. `usersChangePassword`) always passes `{ client: useApiClient(), throwOnError: true }`.

### Resource descriptor

One file per entity in `features/<name>/resources/`: the descriptor plus the type aliases views use. Example (`features/organization/resources/organization.ts`):

```typescript
export type Organization = OrganizationReadSchema
export type OrganizationForm = { id: string | null; name: string; key: string }

export const organizationResource = defineResource({
  key: 'organizations', // query-key root: the plural resource name
  sdk: {
    list: organizationsList,
    retrieve: organizationsRetrieve,
    create: organizationsCreate,
    update: organizationsUpdate,
    destroy: organizationsDestroy,
  },
  // Editable copy for the detail form; called without an item for a new record.
  toForm: (item?: Partial<Organization>): OrganizationForm => ({
    id: item?.id ?? null,
    name: item?.name ?? '',
    key: item?.key ?? '',
  }),
  toCreate: (form) => ({ name: form.name, key: form.key }), // typed as OrganizationCreateSchema
  toUpdate: (form) => ({ name: form.name }), // typed as OrganizationUpdateSchema
  invalidates: ['session'], // other query roots a write makes stale
})
```

- The read type comes from `toForm`'s parameter; `toCreate`/`toUpdate` must return the generated body types (inferred from the SDK functions), so a schema change breaks the build instead of the request. Bodies contain writable fields only; the backend rejects unknown fields on some schemas.
- Leave out SDK functions the API does not have; templates fail loudly when a missing one is needed.
- Validation that needs the UI (`Выберите пользователя`) can throw from `toCreate`.
- Form types are plain objects with `id: string | null`; no hand-written codecs. `/ui` has a local descriptor with an in-memory "SDK" (`features/ui/composables/useUiDemoResource.ts`).

### Query keys and invalidation

| Key | What |
|---|---|
| `['session']` | `GET /auth/me` (`useSession`) |
| `[key, 'list', params]` | Infinite list: `params` = search + filters + `extraParams` + `page_size`; pages are appended by `loadNextPage` |
| `[key, id]` | One record |

A successful save stores the returned record under `[key, id]` and invalidates the `[key]` prefix (lists refetch, every loaded page) plus the `invalidates` roots; delete does the same without refetching the deleted record. Do not patch list caches by hand. Global defaults live in `colada.options.ts` (`staleTime` 30 s). Composables in `shared/api/useResource.ts`:

```typescript
const { items, hasNextPage, loadNextPage, isLoading, error } = useResourceList(organizationResource, {
  params: () => ({ name: search.value }),
})
const { data, refetch } = useResourceItem(organizationResource, () => route.params.id as string)
const { save, remove } = useResourceMutations(organizationResource) // save.mutateAsync(form), remove.mutateAsync(id)
```

### Session and route guards

`useSession()` (`shared/composables/useSession.ts`) exposes `session`, `user`, `organizations`, `isSignedIn` and the `login`, `logout`, `logoutAll` mutations. Login stores the session and drops every cached query of the previous identity; logout clears the session, the organization choice and the cache, then goes to `/auth`. There is no token in the frontend: FastAPI sets and rotates the HttpOnly cookies.

Page meta drives the global middleware (`app/middleware/`):

| Meta | Meaning |
|---|---|
| (none) | App route: `auth.global.ts` requires a session (else `/auth?redirect=<path>`), `setup.global.ts` restores the organization from the session and requires one (else `/home/setup`) |
| `auth: false` | Public page: no session needed, rendered on the server (`/`, `/ui`) |
| `auth: 'guest'` | Signed-out only (`/auth`); a signed-in user goes to `redirect` or `/home` |
| `organization: false` | App route that works before an organization is chosen (`/home/setup`, `/settings/profile`) |

`useSetupStore().restore()` picks the organization stored for the same user, else the only membership; a stored id from another account is ignored. A superuser's stored non-member organization is loaded with `organizationsRetrieve`.

### Rendering

`routeRules` in `nuxt.config.ts`: app routes (`/home/**`, `/recordings/**`, `/projects/**`, `/settings/**`, `/auth`, `/ui`) and the public-but-personal pages `/invite/**` (every lookup counts against the per-IP limit, so it must come from the visitor) and `/oauth/**` are `ssr: false` — the server sends the SPA shell and guards run in the browser. Everything else renders on the server. A public page:

- lives under `pages/` with `definePageMeta({ auth: false })` and mounts a feature view (example: `pages/index.vue` → `features/landing/views/LandingView.vue`);
- sets `useSeoMeta` (title, description, `og:*`);
- may read `useSession()`: during SSR it runs with the forwarded cookie and the result is serialized into the payload, so the client hydrates without a refetch or mismatch. Any other query on a public page must be a GET and must render the same with and without a session;
- use `prerender: true` in `routeRules` instead when the page does not depend on the visitor.

Data on a public page (example: `/s/{token}`, `features/share/`): a Pinia Colada `useQuery` fetches during SSR by itself
(`onServerPrefetch`) and hydrates from the payload without a second request. Set `ssrCatchError: true` so a failed fetch
renders the page's own error state instead of the Nuxt error page, map a 404 to `null` inside the query function and
call `setResponseStatus(event, 404)` there (`useRequestEvent()` captured in setup), and give counted endpoints
`staleTime: Infinity`. Head tags are resolved once on the server after rendering, when the query entry may already be
released: `await refresh()` on the server at the top of the view, copy the SEO values into a plain `ref` and pass
getters to `useSeoMeta` (`title: () => seo.value.title`) instead of reading the query data there.

### Realtime

`useWebSocketService(channel)` (`shared/composables/useWebSocket.ts`) connects to the same origin (`/ws/<channel>`, proxied like `/api/v1`); the browser sends the access cookie with the handshake. The organization channel is `organizations/<organization_id>`. Invalidate the matching query keys in `onMessage` instead of patching data: events carry ids only, and the refetch goes through the visibility-checked API. Example: `features/recording/composables/useRecordingRealtime.ts`, mounted once by `layouts/default.vue` — `recording.updated`/`recording.deleted` invalidate `[recordings, id]` at once and the list prefix debounced (an event per transcribed chunk), `recordings.resync` the whole `recordings` root, `result.updated` `[recordings, id, results]`. Keep data that must not change under the user (a playing presigned audio URL) outside the invalidated prefix (`['recording-audio', id]`).

### Adding a feature end to end

1. Backend endpoint (see [backend-concept.md](backend-concept.md)), then `make gen-client` and commit `openapi.json` + `generated/`.
2. `features/<name>/resources/<entity>.ts`: types and `defineResource` with the generated SDK functions.
3. Views on `AppListTemplate` / `AppDetailTemplate` with `:resource="…"`; custom calls through `useResource*` or an SDK function with `useApiClient()`.
4. A thin page in `pages/`, a drawer item (`app/navigation/settings.ts` for settings); public pages get `auth: false` and SEO meta. `make new-domain` generates steps 2–4 for a settings CRUD entity.
5. Tests for non-trivial descriptor logic or composables (`tests/resource.test.ts` shows the pattern with a real Colada cache).

---

## Views vs components (decompose)

| Layer | Role |
|---|---|
| `views/` | One screen or a large reusable section (list page, detail page) |
| `components/Foo.vue` | One widget used by a view |
| `components/<cluster>/` | Several files that only make sense together |
| `composables/useX.ts` | Logic used by **multiple** views in the feature |

Split when a view starts mixing list + picker + modal + unrelated helpers. Do not wait for a 400-line file.

**Cluster folder** — parent list + row actions + a composable that only they need:

```
features/project/components/member-list/
  ProjectMembersList.vue
  MemberRoleSelect.vue
  useMemberList.ts
```

Keep `composables/useProject.ts` at feature root when many screens share it. Same pattern in the kit: `shared/ui/app/date-picker/` (Vue files + `composables/`).

Existing reference: `OrganizationListView` / `OrganizationDetailView` + `OrganizationPicker.vue` + `OrganizationMembersList.vue` (members list can move into `components/member-list/` when it grows).

---

## Templates

Build screens from `shared/ui/app/` and `shared/ui/template/`. Extend those primitives; do not fork a one-off table.

| Component | Role |
|---|---|
| `AppPageView` / `PageHeader` | Page composition: one `h1`, actions and description, bounded scrolling content; optional controls and footer |
| `AppSection` | Structural grouping with title, `description` and optional actions/back action; no colored surface |
| `AppCard` | Visual surface on the shadcn `card`: `variant` = `outline` (default), `default`, `muted`, `elevated`; `tone` tints surface and border; `padding`, `interactive` |
| `AppListTemplate` | List page or nested list on a `resource` (or local `items`): search, filters, infinite pagination, create, detail as route or modal |
| `AppDetailTemplate` | Form + save/delete (`AppDetailActions`) on a `resource` |
| `AppTemplateActions` | **Two or more buttons in a row.** Do not put several `AppButton`s side by side |
| `AppTabs` / `AppTabPanel` | Sections on a screen. `v-model` is the active tab `value`. `query-key` writes it to the URL. The recording page uses the default `segment` switch, aligned to the content edge (no negative offset). Live: `/ui` |
| `AppMenu` | Overflow, context menu, or custom overlay (`:actions`, `label` for heading). Live: `/ui` → Overlays |
| `AppModal` | Custom modal: `v-model`, `title`, `description` (`subtitle` compatibility), `width`. App-level overlay names use `Modal` |
| `AppConfirmModal` | Confirm/Decline modal: `:confirm` / `:decline`. Built on `AppModal` + `AppTemplateActions`. Live: `/ui` → Overlays |
| `AppTable` / `AppColumn` | Table with declarative `field`, `header`, `format` and scoped `#body`; retained by `AppListTemplate` |
| `AppSelect` | Single/multiple selection, search and pagination; API-backed via `:resource="userResource"` (or a custom `:source`). The trigger never changes with a value or while open (same border and background; placeholder muted, value in the foreground color) and stays one line high: a multi-select shows two chips and «+N» |
| `AppFilterToolbar` | List filter bar: search, fixed fields, compact conditions added through **+**, quick/actions slots |
| `AppFilters` | Internal condition editor; toolbar uses `inline` mode. Specification and `v-model` are shared; feature owns query mapping |
| `AppCheckbox` / `AppSwitch` / `AppRadioGroup` | Choice controls on the shadcn primitives. `AppRadioGroup` takes `:items="[{ label, value }]"` + `v-model` |
| `AppSettingRow` | One settings line: label and description left, control right (`stacked`: full-width control below); hairline between rows. Settings screens stack them instead of cards |
| `AppResultState` | Centered outcome or empty state: icon in a tinted circle (`tone`), title, text, full-width `#actions` |
| `AppBadge` / `AppAlert` / `AppTooltip` | Status chip (`tone` × `solid`/`soft`/`outline`), inline message (`tone`, role alert/status), hover/focus hint |
| `AppProgress` / `AppSkeleton` / `AppScrollArea` | Linear progress with `tone`, loading placeholder lines, bounded area with themed scrollbars |
| `AppImageLightbox` | Mounted once in `app.vue`; open with `useAppImageLightboxStore().open(urls, index)` |
| `AppThemeSwitcher` | Theme (system/light/dark) and palette controls; used in the profile menu and on `/ui` |
| `AppPopover` | Anchored panel for small pickers and forms: `#trigger` (as-child, gets `open`) + content (gets `close`), `v-model:open`, `align`/`side`/`sideOffset`, `contentClass` (`p-0` for panels with their own sections), `preventOpenAutoFocus`; scrolls within the available height; joins the overlay stack |
| `AppEmojiPicker` | Curated emoji grid (`emojiCatalog.ts`, ~64 emoji in 4 groups) in an `AppPopover`; `v-model` is the emoji or `null` («Убрать»); `#trigger` replaces the default button (project icons) |
| `AppMarkdown` | Renders Markdown (AI summaries) safely, see [Markdown](#markdown) |

`templateVariant`: `page` | `section` | `flat-section`. Page templates use `AppPageView`; both nested variants use structural `AppSection`. Do not wrap a page template in another page heading. Use `AppCard` when a nested block needs visual emphasis; `AppBlock` is removed.

```vue
<AppTabs
  v-model="tab"
  query-key="tab"
  :tabs="[
    { label: 'Список', value: 'list' },
    { label: 'Карта', value: 'map' },
  ]"
>
  <AppTabPanel tab-value="list">…</AppTabPanel>
  <AppTabPanel tab-value="map">…</AppTabPanel>
</AppTabs>
```

```vue
<AppModal v-model="open" title="Фильтры">
  …
</AppModal>

<AppConfirmModal
  v-model="confirmOpen"
  title="Удалить?"
  :confirm="remove"
/>
```

**List, navigate to detail**

```vue
<AppListTemplate
  title="Проекты"
  detail-route-name="settings-projects-id"
  :resource="projectResource"
  filter
>
  <AppColumn field="name" header="Название" />
</AppListTemplate>
```

**List owned by a parent, detail in a modal** (`detailItem` is the form from `toForm`)

```vue
<AppListTemplate
  title="Проекты"
  detail-mode="modal"
  template-variant="section"
  :extra-params="{ parent_id: props.parentId }"
  :build-new-item="() => projectResource.toForm({ parent_id: props.parentId })"
  :resource="projectResource"
>
  <AppColumn header="Название" :format="(row) => row.name || '—'" />
  <template #detail-modal="{ detailItem }">
    <AppInput v-model="detailItem.name" label="Название" />
  </template>
</AppListTemplate>
```

**Detail page** (`:id` route param; `new` builds a new form)

```vue
<AppDetailTemplate
  title="Проект"
  :resource="projectResource"
  :back-action="() => navigateTo({ name: 'settings-projects' })"
>
  <template #default="{ item }">
    <AppInput v-model="item.name" label="Название" />
  </template>
</AppDetailTemplate>
```

See `features/organization/views/` and `features/user/views/`. Props worth knowing: `mode` (`page` \| `inline`), `actions-props`, `hide-back-button` (modals), `build-new-item` (defaults to `resource.toForm()`). `AppListTemplate` emits `save` (`{ item, saved, created }`) after a modal save — `saved` is the raw API response (the API token secret is only there).

---

## UI foundations and query state

`AppDetailTemplate` reads the record from the `[key, id]` query and copies it into a form once per record, so background refetches never overwrite edits; a late response for the previous route id cannot replace the open record (keys differ). It shows loading, a Russian error message and a retry action instead of an empty form when retrieval fails. Successful saves replace the form with the server response; creating on a route page swaps `new` for the new id.

In modal mode `AppListTemplate` shows the clicked row at once and replaces it with the fresh `[key, id]` record when that has loaded (`retrieveOnOpen`, default on). Saves and deletes go through `useResourceMutations`, so the list refreshes by invalidation.

Signing out or in as another user drops every cached query (`resetQueryCache`) and the organization choice; nothing from the previous user stays on screen. Logout failures keep the current screen and show an error.

Token forms include `user_id` only when creating a token; edits send the name only. The backend rejects ownership fields on updates.

Keep the direct `vite` 8 development dependency: it gives `nuxt typecheck` the
same Vite types Nuxt and `@tailwindcss/vite` use. Run `pnpm typecheck`
separately from `pnpm build`; the production build does not enable TypeScript
checks. Tooling is described in [Tooling](#tooling).

`shared/ui/shadcn/` contains the local shadcn/Reka primitives. Product views consume `App*` wrappers from `shared/ui/app/`. Styling rules are in [Design system](#design-system). The catalogue at `/ui` is public with static examples.

`AppListTemplate` keeps route/modal detail behavior. `useListData` (template composable) owns search (debounced), filters and `extraParams` and hands them to `useResourceList`; each combination is its own infinite query from page 1. Without a resource (or with `onlyClientSearch`) it filters `items` locally and never requests pages. `AppSelect` keeps its own page requests and selected-item hydration (`resourceSource`); it reloads options every time it opens, keeping the loaded ones on screen until the new page arrives (no spinner flash, no jump).

`AppTable` keeps its header visible for empty, loading and error states. A body slot receives `{ data, item, index }`; buttons and links inside a row do not activate row navigation. Existing `AppColumn` formatting remains available:

```vue
<AppColumn field="name" header="Название" />
<AppColumn header="Описание" :format="(row) => row.description || '—'" />
<AppColumn header="Действия">
  <template #body="{ data }">
    <AppButton label="Изменить" @click="edit(data)" />
  </template>
</AppColumn>
```

`AppListTemplate` accepts `filterSpec` (`ViewFilterSpec`) describing field labels, kinds and supported lookups, `fixedFields` (`ViewFixedField[]`) for permanently displayed controls, and `availableFilters` (field-name array) for the add-filter menu. Omit `availableFilters` to offer all fields; pass `[]` to offer none. Fixed controls remain visible independently of that menu. `v-model:filters` optionally controls the `ViewFilters` record. Conditions join the list query and restart from page 1; reactive `extraParams` take precedence to preserve page scope. Choice fields load options from `resource` (`ViewFilterField.resource`). The toolbar remains outside the page scroll area. Existing `#filters` and `#search-actions` slots work alongside the declarative filters. Backend endpoints must explicitly support each offered field/lookup.

```vue
<AppListTemplate
  :resource="organizationResource"
  search-param="name"
  :filter-spec="{ fields: [{ field: 'key', label: 'Ключ', kind: 'text', lookups: ['icontains', 'exact'] }] }"
  :fixed-fields="[{ field: 'key', mode: 'single' }]"
  :available-filters="['key']"
/>
```

This example keeps an exact-key input visible and offers a contains-key condition through the add menu. Both conditions combine with name search. `AppFilters` and `AppFilterToolbar` in `shared/ui/app/filters/` also remain available independently.

---

## Wiring

**Page** — `pages/settings/projects/index.vue` / `[id].vue`:

```vue
<template><ProjectListView /></template>
<script setup lang="ts">
import ProjectListView from '~/features/project/views/ProjectListView.vue'
</script>
```

**App shell** — `shared/components/layout/AppLayout.vue` is a Notion-style sidebar shell: a fixed sidebar on `md+`
(hidden with its own button; `useSidebar().collapsed` is kept in the `sidebar-collapsed` cookie), a sheet (`AppDrawer
overlay`) on phones opened from a slim top bar, and the page in `<main id="main-content">` (the only `<main>`:
`AppPage` bodies are plain regions), reached by the «Перейти к содержимому» skip link. In the sheet `AppSidebar`
gets `sheet`: a ✕ instead of «Скрыть боковую панель» and no keyboard hints on items. `app.vue` mounts a
`NuxtLoadingIndicator` in `--primary`; `app/error.vue` is the Russian 404/500 page. Layouts fill its slots and may import
features (the architecture guard forbids it only for `shared/**`): `sidebar-header` (organization switcher or «Назад»),
`sidebar` (`AppSidebarNav` with `SidebarSection[]`: optional title, items `{ to, label, icon, hint }`, a heading
`action` such as «+», an `empty` text), `sidebar-footer` (settings link, `AppSidebarUser`) and `topbar` (what the top
bar shows on phones). Items may show an `emoji` instead of the icon and a muted `trailingIcon` (+ `trailingLabel` for
screen readers: the lock of a private project). A section with `collapsibleId` folds from its heading (remembered in
the `sidebar-folded` cookie), `limit` shows that many items plus «Показать ещё N» (the active item always stays
visible), `loading` shows skeleton rows instead of the `empty` text. One item is active: the route name matches (or
nests under it), the item's own params and query match, so `?personal=1` beats the bare route and only the open project
is active. Items are 44px tall on phones, 32px on desktop. The workspace sidebar is data in `app/navigation/workspace.ts`;
`layouts/default.vue` adds «Поиск» (an item without `to` is a button with `onClick`; it opens the ⌘K dialog), «Проекты»
from `features/project/composables/useProjectsSidebar.ts` (and mounts the «Новый проект» modal its «+» opens), the
quick search dialog, the upload tray and the recordings realtime listener.

**Settings sidebar** — data: `app/navigation/settings.ts` (`settingsNavigation`), rendered by `layouts/settings.vue`
in groups (`settingsSections`: organization, account, instance; `section` defaults to organization). Add an entry above
the marker line (`make new-domain` does it); `adminOnly: true` shows it to org owners/admins only, `superuserOnly: true`
to superusers only:

```typescript
import { Folder } from '@lucide/vue'
{ to: { name: 'settings-projects' }, label: 'Проекты', icon: Folder },
```

Resources are plain modules: import them where they are used; there is no registry.

Route names follow the file path: `settings/projects/[id].vue` → `settings-projects-id`.

## Async actions and labels

A **row** of buttons → `AppTemplateActions` (`action`, optional `successNotification`). It already handles per-button loading. A **single** click or modal → `useActionState`: bind `:loading="state.loading.value"` and `@click="state.execute"`. Do not add a parallel `ref` + `try/finally`. Overflow / right-click → `AppMenu`. Live: `/ui` (Layout + Overlays).

```ts
const saveState = useActionState(async () => {}, { successNotification: 'Сохранено' })
```

Feature label maps: a composable like `composables/useProjectLabels.ts` (`LabelConfig` + `getXxx()`), not ad hoc `Record<string, string>` in every component.


## Notifications and checks

Use `useToast()` with `toast.default` for ordinary confirmations. `useNotify` is removed. `AppToaster` is mounted once at application level; errors can use `toast.error`. Its classes carry `!` because vue-sonner's stylesheet is unlayered and would otherwise beat Tailwind utilities (compact toast, close button inside the top-right corner, as in Tasker).

```ts
const toast = useToast()
toast.default('Сохранено')
toast.error('Не удалось сохранить', { description: 'Попробуйте ещё раз' })
```

`useActionState` and template actions retain their loading and notification contracts. Avoid sending a second toast when the action helper already handles it.

Before handing off, run `make lint` and `make check` from the repository root (see [Tooling](#tooling)).

## Tooling

Vite+ (`vite-plus`, pinned) runs formatting, linting and tests; Nuxt still owns dev, build and typecheck.

| Script (`frontend/`) | What it does |
|---|---|
| `pnpm fmt` / `pnpm fmt:check` | Oxfmt: no semicolons, single quotes, width 120, trailing commas, one attribute per line, Tailwind class order (`cn`, `cva`, `clsx` arguments too) |
| `pnpm lint` / `pnpm lint:fix` | Oxlint over all TS/JS/Vue scripts, then ESLint over `*.vue` templates; warnings fail |
| `pnpm test` | `vp test run` (Vitest, happy-dom). Tests live in `tests/` and import from `vite-plus/test` |
| `pnpm typecheck` | `nuxt typecheck` (vue-tsc, TypeScript 6) |
| `pnpm check:architecture` | Layer guard, see below |
| `pnpm check:unused` | knip with the Nuxt plugin: unused files and dependencies (`knip.jsonc`; deliberate keeps are listed under `ignore` with a reason) |
| `pnpm ui:add <name>` | Adds a shadcn-vue primitive, see [Adding a shadcn primitive](#adding-a-shadcn-primitive) |
| `pnpm gen:api` / `pnpm gen:api:check` | Regenerate the API client from `openapi.json` / fail when the committed one is stale (see [Data layer](#data-layer)) |
| `pnpm check` | `fmt:check` + `lint` + `typecheck` + `test` + `gen:api:check` + `check:architecture` + `check:unused` — what CI runs |

From the repository root: `make lint` fixes and formats backend and frontend, `make check` runs every CI check without changing files (`make check-frontend BUILD=1` adds `nuxt build`).

**Config.** `frontend/vite.config.ts` holds the `fmt`, `lint` and `test` blocks and is read only by `vp`. Nuxt runs Vite with `configFile: false`, so this file never affects the app; `nuxt dev` prints a one-line `NUXT_B5004` warning about it, which is expected. App build settings belong in `nuxt.config.ts`.

**Why ESLint stays for `*.vue`.** Oxlint lints the `<script>` blocks of SFCs but not `<template>`. `eslint.config.mjs` therefore runs `eslint-plugin-vue` (`flat/recommended`) on `*.vue` only, turns off its layout rules (Oxfmt owns layout), and uses `eslint-plugin-oxlint` to switch off every rule Oxlint already reports. Deliberate exceptions: `vue/valid-template-root` (redirect pages and renderless components have empty templates), `vue/require-default-prop` (optional props are `prop?: T`), `vue/multi-word-component-names` (shadcn names). Add script rules to the `lint` block in `vite.config.ts`, not to ESLint.

**Type-aware Oxlint is off.** Its type checker (tsgolint) cannot resolve types exported from `.vue` files, so those types become `any` and produce false positives; `nuxt typecheck` covers types instead.

**Architecture guard.** `scripts/check-architecture.mjs` checks explicit imports in `app/`: features never import `reka-ui` or `~/shared/ui/shadcn` (use `App*` wrappers); `shared/**` never imports `features/**`; `shared/ui/shadcn` never imports `shared/ui/app` or `shared/ui/template`. The generated client (`shared/api/generated/`) is skipped. `KNOWN_VIOLATIONS` is empty; keep it that way. When shared UI needs feature content, expose a slot and fill it from `app/layouts` or a page (example: the header `context` slot holds `OrganizationPicker`).

**Formatter caveat.** With `semi: false`, Oxfmt drops the `;` between statements of an inline handler (`@save="a(); b = false"`), which Vue cannot parse. Write multi-statement handlers as a function (`@save="() => { a(); b = false }"`) or a method.

## Design system

### Tokens and theming

All design values live in `app/assets/styles/theme.css`; there is no SCSS.

- `:root` is the light theme and `[data-theme='dark']` the dark one (set by `@nuxtjs/color-mode`). Both define
  the shadcn semantic tokens directly (`background`, `foreground`, `card`, `popover`, `primary`, `secondary`,
  `muted`, `accent`, `destructive`, `border`, `input`, `ring`, `sidebar-*`, `chart-1..5`) plus `border-strong`,
  `field-hover`, `row-hover`, status tones `success`/`info`/`warning`/`destructive` with `-foreground`,
  `--overlay-shadow`, `--z-overlay`, `--radius`, control heights `--size-control-xs|sm|md|lg` and control text
  sizes `--font-size-control-*`.
- `app/assets/styles/tailwind.css` imports the file and exposes every token through `@theme inline`, so
  components use utilities: `bg-field-hover`, `text-success`, `border-border-strong`, `shadow-overlay`,
  `z-overlay`, `h-control-md`, `size-control-sm`, `text-control-sm`, `rounded-lg` (radii derive from `--radius`).
  Never write `bg-[color:var(--…)]` or set geometry with inline `style`. Control size class maps live in
  `shared/ui/app/types/control.ts`.
- `cn()` (`shared/lib/utils.ts`) extends tailwind-merge with the custom scales; register new scales there or
  merges will drop classes.
- Rem base: `--font-size-root: 93.75%` (15px by default, so `text-sm` ≈ 13px, still following the user's browser
  font size). Every Tailwind spacing and type utility is rem-based, so this one value scales the whole UI.
- Fields: inputs, textareas and select triggers share `shadow-xs`; focus only darkens the border to the neutral
  `border-border-strong` (never the accent `ring`), no focus ring. Every `AppSelect` has a search field: local
  `options` are filtered on the client, a `resource`/`source` searches the API. Overlays (menus, popovers, select lists, date picker) use `shadow-overlay`, a soft shadow.
- Font: Inter (variable) is self-hosted via `@fontsource-variable/inter` (imported in `app.vue`); the stack in
  `--app-font-sans` prefers the system UI font on Apple platforms.

**Palettes.** `[data-palette=…]` blocks override only `--primary`, `--primary-foreground` and `--ring`
(`sidebar-primary` follows). Shipped: `neutral` (default), `blue`, `violet`, `green`, `orange`. A first-time visitor (signed in or not: landing,
`/auth`, a shared recording) gets the system color mode and the neutral accent. `useTheme()`
returns `mode` (`system`/`light`/`dark`), `resolvedMode` and `palette`; both choices are stored in cookies
(`colorScheme`, `palette`), and the palette cookie is written only after an explicit choice. `app.vue` renders `<html data-palette>` during SSR and an inline head script
(`shared/lib/theme.ts`) applies it on client-only routes, so there is no flash.

**Re-branding a fork.** Change the neutral surfaces in `theme.css` if needed, add or edit a palette block in both
themes, list it in `PALETTES` (`shared/lib/theme.ts`) and give it a label/swatch in `AppThemeSwitcher.vue`. To
change the default, set `DEFAULT_PALETTE`. Check the result on `/ui` → Tokens in both themes.

### Adding a shadcn primitive

```bash
cd frontend
pnpm ui:add tooltip            # wraps: pnpm dlx shadcn-vue@2.8.2 add tooltip --yes
```

`components.json` points the CLI at `shared/ui/shadcn/<name>/` (style `new-york`, base color neutral, CSS
variables). The script also rewrites the registry's broken `cn` import to `~/shared/lib/utils`, removes the
stray `cn` package and formats the output. Then review the files: replace `z-50` with `z-overlay`, keep
semantic token classes, export everything from `<name>/index.ts` (never import a primitive's `.vue` file from
outside its folder). Finally wrap it as `App*` in `shared/ui/app/` (Russian defaults, `tone`/`size` vocabulary),
use it somewhere real or in `/ui` (knip fails on unused files) and add a demo to the catalogue.

### Icons and dates

- Icons: `@lucide/vue` components only (`import { House } from '@lucide/vue'`; pass `:icon="House"`).
  `AppIcon` takes a component, a `size` (`xs`–`lg` or px) and an optional `tone`. String icon names exist only
  as data in `AppAppearancePicker`. Spinners use `AppIcon loading` (Lucide `LoaderCircle`).
- Dates: `@internationalized/date` plus `shared/lib/dateFormat.ts` (`formatDatePattern` / `parseDatePattern`,
  Day.js-style tokens). `useDate()` returns wall-clock `CalendarDateTime` values, formats `shortcut` labels
  (`Сегодня`, `2 окт`) or patterns, and keeps SSR hydration stable with a shared clock/offset.
- Deep copies: `deepClone` from `shared/lib/clone.ts` (handles Vue proxies); arrays: `.at(-1)`.

## UI layers and visual review

Dependencies point one way: `shared/ui/shadcn` → `shared/ui/app` → `shared/ui/template` → `features`. shadcn primitives know nothing about resources or routes; features use `App*` and template components, never `shared/ui/shadcn` directly. `AppListTemplate` owns CRUD, search and pagination (through the resource); `AppTable` only renders.

Automated checks do not replace a browser pass. For a UI change, open `/ui` and every affected screen at **390px, 768px and 1440px** in **both themes** and check:

- empty, loading, error and retry states; long names; disabled and loading buttons;
- search, the next page and back navigation; create/edit/delete in route and modal modes;
- menus and date pickers inside modals and drawers: clipping, stacking, Escape, Tab and focus return;
- no double scroll, overlaps or page-wide horizontal scroll; no hydration warnings or console errors after a reload.

## Button and table variants

`AppButton` has one vocabulary:

| Prop | Values |
|---|---|
| `variant` | `default` (main action; filled with `primary`), `secondary` (filled neutral companion: cancel, back), `outline` (toolbar: filters, export), `ghost` (row and menu actions), `link`, `destructive` (final confirmation) |
| `size` | `xs`, `sm`, `md` (default), `lg`; `icon-xs`, `icon-sm`, `icon`, `icon-lg`. An icon-only button picks the square size of its row height automatically |
| `icon` / `icon-position` | A Lucide component; `start` or `end` |
| `text-variant` | `base` or `muted` (muted until hover/focus) |
| `loading`, `disabled`, `fluid`, `to` | State, full width, router navigation |
| `href`, `external` | A real link (`<a href>`) styled as a button: public pages, downloads, external sites; `external` opens a new tab with `rel="noopener noreferrer"` |

Icon-only buttons need `aria-label` (or `title`); dev builds warn when it is missing. Geometry comes from the
size tokens through cva classes (`appButtonPrimitiveSize` maps `md` to the shadcn `default`); never set it with
inline styles. PrimeVue-era props (`severity`, `text`, `outlined`, `iconPos`, `small`/`large`) are gone.

### Dialogs, settings column, switches

- **Dialog buttons** have one layout, enforced by `AppModal`'s footer (`AppModalFooter` provides `IN_MODAL_FOOTER`):
  on phones the buttons stack full-width with the primary on top, from `sm` they sit right-aligned at their natural
  width, cancel first. `AppTemplateActions` inside the footer follows it and ignores `full-width`/`fluid`; plain
  `AppButton`s in the footer get it from the flex layout. List cancel first, the primary last; do not add your own
  wrappers or width classes.
- **One page shell** (rules and reasons: [ui-audit.md](ui-audit.md)). `shared/ui/app/pageContainer.ts` holds the
  shared geometry: `PAGE_GUTTER_CLASS` (`px-4 md:px-10`), `PAGE_TOP_CLASS` (`pt-6 md:pt-10`), `PAGE_TITLE_CLASS`
  (the h1 of every page) and `PAGE_ACTIONS_CLASS` (header actions, 44 px on phones). Do not hand-write these on a page.
- **Page actions.** Workspace pages (`AppDocumentPage`) have a Notion-like top bar over the whole main area: where you
  are on the left (`#lead`: the icon and title, or «← Все записи › запись»), actions on the right — all `ghost`
  («Загрузить», «Поделиться»), the «⋯» menu last. The bar does not scroll. With the sidebar hidden it also holds
  «Показать боковую панель» and `AppLayout` drops its own desktop header. Settings pages keep actions in the page
  header at the top right of the column: the primary action first (`md`, with an icon: «Новый проект»), the «⋯» last.
  Toolbars hold search and filters only.
- **Settings column**: `layouts/settings.vue` provides `PAGE_CONTAINER_CLASS` (`max-w-(--page-width)`, the same
  column as the workspace pages). In a container `AppPage` is one scrolling document: header (`PageHeader`: title,
  description, actions), `controls` sticky at the top, body; no divider. It owns the paddings (`contentClass` is
  ignored); views do not set their own max width or `content-class`.
- **Page width**: one token, `--page-width` (63rem), for every page: lists, project, recording, settings and the
  public share page; use `max-w-(--page-width)` instead of a fixed `max-w-*`.
- **Document pages**: `AppDocumentPage` (`shared/ui/template`) is the workspace page — a lead (default: icon and title;
  or `#lead`, e.g. a back button) with `#actions` on the right — both in the top bar — then, in a `max-w-(--page-width)`
  column, an optional large icon (`icon`/`#icon`), the title (`#title`, or `#heading` for a custom h1), `#meta`
  badges, a description and the content; `#state` replaces the document for
  loading/not-found (same column), `#footer` stays fixed under the scroll (the audio player), and the scrolling
  element is exposed as `scroller`. «Все записи» / «Личные» / «Корзина», the project page and the recording page use it.
- **Creation is a modal** everywhere: tags, projects, templates, tokens, invitations (`InviteCreateModal`, two steps:
  form → the link shown once), organizations and users (`AppListTemplate create-in-modal` + `#detail-modal`; rows
  still open their route page). Never put a create form inline on a page.
- **One toolbar, one height**: search, filter selects and buttons in a page toolbar are all `md` (44 px on phones).
  `sm` is for controls inside rows and section headers (`AppListTemplate` sections get an `outline sm` create button).
- **Chips in dense rows**: `TagChipList` (`features/tag`) shows whole chips that fit a `budget` (rem) and «+N»; the
  parent gives the slot a fixed width. Never let a chip truncate next to other chips, never vary the column width.
- **Theme on public pages**: `AppThemeToggle` (one icon button, light ↔ dark) on `/s/{token}` and the landing page.
- **Switch**: off is a light knob on a muted track (`--switch-track`, `--switch-thumb` in both themes), on is the
  brand color. A switch without a visible `<label>` gets `aria-label`.
- **Empty states** speak human: pass `empty-text` to lists (`AppTable`/`AppList` default «Здесь пока пусто»).
- **Avatars and names**: always `userDisplayName(user)` («Имя Фамилия», else the email) for both the text and
  `AppAvatar :name`, so initials match everywhere.

`AppTable` defaults to `variant="default"`: transparent header, no outer border or
rounded corners; row separators remain. `variant="outline"` adds the border,
rounded corners and tinted header. `AppList` and `AppListTemplate` forward
`table-variant="outline"` when the framed style is needed. The catalog `/ui` shows
both variants with the same data and loading/empty/error states.

### Filter toolbar

Use `AppFilterToolbar` for a list search-and-filter bar, not a standalone vertical
`AppFilters`. `v-model` holds conditions,
`v-model:search` holds search text, `spec` supplies fields (choice fields may name a `resource`).
`fixedFields` pins single/multiple/optional controls; their keys are excluded from
repeated dynamic conditions. `visibleFields` / `hiddenFields` restrict available fields.
Slots `primary`, `fixed-<field>`, `quick`, `actions` supply feature-specific tools.
`wrap` wraps conditions on narrow screens; `alwaysShowAdd` keeps the plus visible.
Feature-specific pickers and display settings are not part of this generic filter
bar; a feature provides them through the slots.

### Semantic tones

`shared/ui/app/tone.ts` is the only semantic color map: `TONES` = `neutral`, `muted`, `primary`, `success`,
`info`, `warning`, `destructive`, and `toneVariants({ tone, appearance })` with appearances `text`, `soft`,
`outline`, `tinted` (card surface), `solid` and `stroke`. `AppCard`, `AppDataLabel`/`AppLabel`, `AppBadge`,
`AppAlert`, `AppIcon`, `AppTextButton`, `AppProgress` and `AppCircularProgress` all take `tone`; label configs
(`AppLabelConfig`) use `{ label, icon, tone }`. Do not add per-component color maps. `primary` is the brand
(palette) color; `accent` is an interactive hover/active surface, not a status. Field captions stay muted. The
`/ui` catalog has directly authored English copy and displays actual prop names. `AppColorPicker` keeps its own
list of user-selectable colors (data, not theme).

### Typography and appearance pickers

AppTitle renders the `as` heading tag and maps sm/md/lg/xl to text-sm/text-base/text-xl/text-3xl. PageHeader
defaults to h1/xl; AppSection defaults to h2/lg. Both honor titleSize through AppTitle.
AppAppearancePicker defaults to the full, dynamically imported Lucide catalog;
custom loadIcons/currentIcon/normalizeIcon props remain supported. The grid is
virtualized and searchable by icon name. AppColorPicker wraps `vue-color` (ChromePicker) and maps its variables
to theme tokens, including portalled popovers. Emoji are picked with `AppEmojiPicker` (a small curated grid, no emoji
database); AppAppearancePicker has no emoji mode.

### Markdown

`AppMarkdown :source` renders AI summaries. `shared/lib/markdown.ts` parses a small Markdown subset into a tree
(headings, paragraphs with line breaks, nested lists with task items `- [ ]`/`- [x]` shown as read-only check marks, quotes, fenced code, rules, tables; bold, italic, strikethrough,
inline code, links and bare http(s) URLs) and the component renders that tree with `h()`. There is no `v-html`
anywhere on this path: raw HTML in the source stays text, only `http(s)://` and `mailto:` become links
(`target="_blank" rel="noopener noreferrer nofollow"`). Extend the parser (and `tests/markdown.test.ts`) for new syntax;
never render model output with `v-html`.

### Recording screens (feature `recording`)

Patterns worth reusing, all in `features/recording/`:

- **One list, fixed scope.** `components/list/RecordingList.vue` serves «Все записи», «Личные», «Корзина» (`{ deleted: true }`) and the project page;
  the screen passes `fixed` filters (`{ personal: true }`, `{ project_id }`) that are neither shown nor editable.
  Editable filters live in the URL through `composables/useRecordingFilters.ts` (`?q=&project=&tag=&author=&status=`);
  the toolbar and the list each call it, so there is no shared mutable prop. Rows are grouped by day
  (`useRecordingGroups`, `useDate`).
- **Container queries for dense rows.** The list root is `@container`; rows and the toolbar switch between the narrow
  layout (meta line, then a line of chips under the title) and fixed left-aligned columns (tags `w-52`, project
  `w-40` from `@5xl`, duration, author, time) with `@3xl:` / `@5xl:`, so the sidebar and the project page width count,
  not the viewport. Touch heights (`max-md:h-11`) stay viewport-based. «Загрузить» is a page header action: the list
  exposes `pickFiles()` and the view calls it.
- **Optimistic writes on one record.** `useRecordingMutations.patch(id, body, optimistic)` writes the detail cache at
  once, replaces it with the response, rolls back with a toast on failure and invalidates the lists. Sub-resources of
  a record (`[recordings, id, events|results|share]`) are `useQuery`s in `useRecordingDetail.ts`.
- **Uploads outside the page.** `stores/useUploadStore.ts` (Pinia, lives for the tab) runs browser uploads with
  `utils/audioUpload.ts` (XHR for progress, multipart with three workers and retries); `UploadTray` is mounted by the
  default layout. `utils/` holds plain helpers of a feature (`lib/` is ignored by git in this repo).
- **Bulk and drag.** `composables/useRecordingBulk.ts` moves, retags and deletes one or many recordings (one request
  each, four at a time, one toast with «Отменить»); the detail page, the list's `RecordingBulkBar` and drops onto
  sidebar projects (`SidebarItem.drop`, wired in `layouts/default.vue`) all use it. `RECORDING_DRAG_TYPE` marks the drag.
- **⌘K palette.** `components/search/QuickSearchDialog.vue` + `composables/useQuickSearch.ts`: a screen adds its own
  commands with `usePageCommands(() => ({ title, commands }))`; «Недавние» come from `useRecentRecordings`
  (localStorage per organization). The dialog content has no closing animation so `<body>` gets pointer events back
  at once.
- **Pickers.** `ProjectPicker`/`TagPicker` take a `#trigger` slot (bulk bar); `ProjectPicker` is a combobox over the
  locally loaded projects.
- **Shared formatting.** `formatClock` / `formatDuration` (`shared/utils/duration.ts`) and `userDisplayName`
  (`shared/utils/userDisplayName.ts`) are auto-imported; do not add per-feature copies. Error texts by stable
  `error_code` live in `processingErrorText` (`useRecordingLabels.ts`).

### Tag palette

Tags use their own Notion-like palette, not the status tones: `--tag-<color>` (chip background) and
`--tag-<color>-foreground` for `gray | brown | orange | yellow | green | blue | purple | pink | red` in both themes,
exposed as `bg-tag-blue text-tag-blue-foreground`. `features/tag/composables/tagColors.ts` (`TAG_COLORS`,
`tagChipClass`) and `TagChip` are the only places that map a `TagColor` to classes.

AppDrawer slides in (200ms) and out (300ms) from its `side`; overlay drawers take `contentClass` (merged last, e.g. `p-0`) and `closeable` (the corner close button) and uses only the inner edge border (right for left drawers, left for right drawers). Modal headers use the shared header gap between title and description. Motion respects reduced-motion preferences.

Overlay drawers participate in the same opening-order stack as modals, menus and
pickers. A surface opened inside a drawer appears above it; interacting with that
surface keeps the drawer open. Inline drawers do not reserve an overlay layer.
The Overlays catalogue demonstrates a date picker and a modal opened from a drawer.

### Page regions and automatic list pagination

`AppPageView` builds on `AppPage` with these regions: `header` (custom whole header),
`subheader` (below the header, before the divider), `controls` (after the divider),
`default` (scrolling body), and `footer` (fixed bottom region). The standard
`PageHeader` accepts `prefix`, `title`, `title-append`, and `actions`; AppPageView
forwards these slots. `subtitle` remains an alias for `subheader`, with subheader
winning when both are supplied. Description appears once in the standard header.
`titleSize`, `backAction` and `contentClass` configure the heading, return action
and body spacing. `/ui` → Layout shows every region. (In Hearfolio `pages/home/index.vue` redirects to `/recordings`, keeping the query: `/home` stays the post-login
target of the template guards.)

`AppListTemplate` enables `infiniteScroll` by default for server-backed queries.
The existing `AppInfiniteScroll` observes a sentinel within the visible scroll
area and appends the next confirmed page. It waits during loading, stops at the
last page or error, and offers a manual retry. A configured `scrollHeight` bounds
the list and its sentinel together. Local/onlyClientSearch lists do not request
more pages. Set `:infinite-scroll="false"` for manual “Показать ещё” pagination.
Organization list/setup pass `search-param="name"` to match their backend filter. Keep search
and filter resets in `useListData`; do not add another observer in feature views.

### Fixed list tools, table edges and profile layout

Page-mode `AppListTemplate` puts search, `search-actions` and `filters` in
AppPageView's fixed `controls` region. `AppListToolbar` owns their shared layout;
AppList hides its inline toolbar in page mode to avoid duplicate controls. Nested
lists keep the same toolbar inside their section, sticky within its scroll area.
Search/query/pagination state remains owned by useListData.

Page table lists default to `tableBleed=true`: `-mx-3 md:-mx-4` compensates for the
standard AppPageView body padding and places the table against the page edges.
Set `:table-bleed="false"` to retain the body gutters. List mode and section/flat-section
variants keep their own spacing. Controls retain their separate page gutters.

AppButton accepts `textVariant` (`base` by default, or `muted`). Base preserves the
button variant's existing text color. Muted uses `text-muted-foreground` until hover
or keyboard focus, when the variant's normal text color returns, including the
inverted text of default/primary/destructive buttons. AppTemplateActions forwards
this prop through its actions. The UI catalogue shows both text variants.

The profile route is a thin wrapper for `UserProfileView`, which uses AppPageView
for the heading, description, body padding and scrolling content. The header product
name uses muted text at rest and foreground on hover. Home has no example badge.
