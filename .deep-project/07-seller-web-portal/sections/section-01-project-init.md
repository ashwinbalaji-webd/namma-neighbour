Perfect! I have all the context I need. Now I'll generate the section-01-project-init markdown content based on the prompt requirements. This section needs to include tests first (from claude-plan-tdd.md), implementation details (from claude-plan.md), and background context.

# Project Initialization — Section 01

## Overview

This section establishes the foundational project structure for the Seller Web Portal. It covers Next.js application setup, shadcn/ui component library installation, environment variable configuration, and test infrastructure initialization. This section is a prerequisite for all other implementation work.

**Deliverables:**
- Next.js 14 application with App Router and TypeScript
- shadcn/ui initialized with required components
- Environment variables configured
- Jest + React Testing Library setup
- MSW v2 mock server initialized

---

## Tests

### What to Test

Based on the TDD plan, this section includes smoke tests to verify:
1. Next.js app structure is correct (app/, components/, lib/ directories exist)
2. Tailwind CSS utilities are available and applied
3. shadcn/ui Button component renders successfully
4. Environment variables (`DJANGO_API_URL`, `JWT_SECRET`, `NEXT_PUBLIC_APP_URL`) are loaded
5. Jest is properly configured with next/jest transformer
6. testEnvironment: jsdom is set for component tests
7. MSW server setup is in place for mocking /api/proxy/* routes
8. Test utilities (render, screen, fireEvent, userEvent) are importable

### Test Files to Create

1. **`__tests__/setup.test.ts`** — Jest configuration and MSW setup verification
2. **`__tests__/components/Button.test.tsx`** — shadcn/ui component smoke test

### Stub Test Implementation

Create test file stubs with passing assertions that verify tooling is operational:

```typescript
// __tests__/setup.test.ts
describe('Jest Configuration', () => {
  it('should have jsdom testEnvironment configured', () => {
    expect(typeof window).toBe('object');
  });

  it('should have next/jest transformer loaded', () => {
    // Verify TypeScript support
    const tsExtensions = require('typescript-jest-example');
    expect(tsExtensions).toBeDefined();
  });

  it('should load environment variables', () => {
    expect(process.env.DJANGO_API_URL).toBeDefined();
    expect(process.env.JWT_SECRET).toBeDefined();
  });
});

describe('MSW Setup', () => {
  it('should have MSW server configured', () => {
    // Import server to verify it initializes without error
    const { server } = require('../__tests__/mocks/server');
    expect(server).toBeDefined();
  });
});
```

```typescript
// __tests__/components/Button.test.tsx
import { render, screen } from '@testing-library/react';
import { Button } from '@/components/ui/button';

describe('shadcn/ui Button', () => {
  it('should render without crashing', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('should apply Tailwind CSS classes', () => {
    const { container } = render(<Button>Test</Button>);
    const button = container.querySelector('button');
    expect(button).toHaveClass('inline-flex');
  });
});
```

---

## Implementation Details

### 1. Initialize Next.js Application

Run the scaffolding command:

```bash
npx create-next-app@14 seller-web \
  --typescript \
  --tailwind \
  --app \
  --src-dir \
  --eslint
```

Configure the following during prompts:
- TypeScript: **Yes**
- Tailwind CSS: **Yes**
- App Router: **Yes**
- src/ directory: **Yes**

### 2. Next.js Project Structure

After initialization, the directory structure should look like:

```
seller-web/
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── (seller)/          # Group for seller routes
│   │   ├── (admin)/           # Group for admin routes
│   │   ├── api/               # API routes
│   │   └── login/
│   ├── components/
│   │   └── ui/                # shadcn/ui components
│   ├── lib/
│   │   ├── utils.ts
│   │   ├── queryClient.ts
│   │   └── api.ts
│   ├── hooks/
│   │   └── useAuth.ts
│   ├── middleware.ts
│   └── types/
├── __tests__/
│   ├── setup.test.ts
│   ├── mocks/
│   │   ├── handlers.ts
│   │   └── server.ts
│   └── components/
├── jest.config.ts
├── jest.setup.ts
├── next.config.js
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

### 3. Install shadcn/ui

Initialize shadcn/ui with New York style and slate colors:

```bash
cd seller-web
npx shadcn-ui@latest init
```

When prompted:
- Style: **New York**
- Base color: **Slate**
- CSS Variables: **Yes**

### 4. Install Required shadcn/ui Components

Install the following components upfront:

```bash
npx shadcn-ui@latest add button input form select checkbox switch tabs dialog table badge card separator progress textarea label
```

Also add the toast notification component (Sonner):

```bash
npm install sonner
```

Create a basic toast provider component at `src/components/providers/ToastProvider.tsx`:

```typescript
'use client';

import { Toaster } from 'sonner';

export function ToastProvider() {
  return <Toaster position="bottom-right" richColors />;
}
```

Update `src/app/layout.tsx` to include the ToastProvider.

### 5. Environment Variables

Create `.env.local` in the project root with the following variables:

```
DJANGO_API_URL=http://localhost:8000
JWT_SECRET=your_secret_here_same_as_django_signing_key
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

Update `next.config.js` to allow these environment variables:

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  // Environment variables are automatically available in server components
  // and API routes. Prefix with NEXT_PUBLIC_ to expose to browser.
  env: {
    DJANGO_API_URL: process.env.DJANGO_API_URL,
    JWT_SECRET: process.env.JWT_SECRET,
  },
};

module.exports = nextConfig;
```

**Note:** `JWT_SECRET` is server-only and should never be exposed to the browser. Only use it in middleware.ts and API routes.

### 6. Jest Configuration

Create `jest.config.ts` at the project root:

```typescript
import type { Config } from 'jest';
import nextJest from 'next/jest';

const createJestConfig = nextJest({
  // Provide the path to your Next.js app to load next.config.js and .env files in your test environment
  dir: './',
});

const config: Config = {
  coverageProvider: 'v8',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  testMatch: ['**/__tests__/**/*.test.ts', '**/__tests__/**/*.test.tsx'],
};

export default createJestConfig(config);
```

### 7. Jest Setup File

Create `jest.setup.ts` at the project root:

```typescript
// jest.setup.ts
import '@testing-library/jest-dom';

// Import MSW server and enable request interception for all tests
import { server } from './__tests__/mocks/server';

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

### 8. MSW v2 Mock Server Setup

Create the MSW handler file at `__tests__/mocks/handlers.ts`:

```typescript
// __tests__/mocks/handlers.ts
import { http, HttpResponse } from 'msw';

export const handlers = [
  // Placeholder handlers — these will be expanded in later sections
  http.post('/api/proxy/*', () => {
    return HttpResponse.json({ success: true });
  }),

  http.get('/api/proxy/*', () => {
    return HttpResponse.json({ success: true });
  }),
];
```

Create the MSW server at `__tests__/mocks/server.ts`:

```typescript
// __tests__/mocks/server.ts
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
```

### 9. TypeScript Configuration

Update `tsconfig.json` to include the path alias `@/*`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictPropertyInitialization": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src", "__tests__"],
  "exclude": ["node_modules"]
}
```

### 10. Update package.json Scripts

Ensure the following test scripts are present in `package.json`:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test": "jest",
    "test:watch": "jest --watch",
    "test:coverage": "jest --coverage"
  }
}
```

### 11. Install Required Dependencies

Install all additional dependencies:

```bash
npm install @tanstack/react-query @hookform/resolvers zod react-hook-form next-themes jose
npm install --save-dev @testing-library/react @testing-library/jest-dom @types/jest jest jest-environment-jsdom msw typescript-eslint
```

---

## Files to Create/Modify

**Files to Create:**

- `/seller-web/jest.config.ts` — Jest configuration
- `/seller-web/jest.setup.ts` — Jest setup with MSW
- `/seller-web/__tests__/setup.test.ts` — Configuration verification tests
- `/seller-web/__tests__/components/Button.test.tsx` — shadcn/ui smoke test
- `/seller-web/__tests__/mocks/handlers.ts` — MSW request handlers (placeholder)
- `/seller-web/__tests__/mocks/server.ts` — MSW server setup
- `/seller-web/src/components/providers/ToastProvider.tsx` — Toast notification provider
- `/seller-web/src/lib/utils.ts` — Utility functions (shadcn/ui setup)
- `/seller-web/.env.local` — Environment variables

**Files to Modify:**

- `/seller-web/tsconfig.json` — Add path aliases
- `/seller-web/next.config.js` — Environment variable configuration
- `/seller-web/src/app/layout.tsx` — Add ToastProvider
- `/seller-web/package.json` — Test scripts and dependencies

---

## Validation Checklist

After completing this section:

- [ ] `npm test` passes (at least setup.test.ts and Button.test.tsx)
- [ ] `npm run dev` starts without errors
- [ ] `http://localhost:3000` loads the default Next.js page
- [ ] `src/app/`, `src/components/`, `src/lib/` directories exist
- [ ] `.env.local` file exists with all required environment variables
- [ ] shadcn/ui Button renders in a page
- [ ] Jest detects and executes tests in `__tests__/` directories
- [ ] MSW server initializes without error in test setup

---

## Dependencies on Other Sections

**None.** This section is foundational and has no dependencies.

---

## Blocks

This section blocks all other sections (01–14). No implementation can proceed until the project is initialized.

---

## Notes

- **Environment variables:** `JWT_SECRET` is sensitive — never commit `.env.local` to version control. Document in `.env.example` without the actual value.
- **shadcn/ui:** Installing components upfront avoids repeated `npx shadcn-ui@latest add` calls. Additional components can be added as needed in later sections.
- **MSW setup:** The handlers file will be expanded significantly in later sections (section-02 auth, section-07 dashboard, etc.). The placeholder handlers ensure MSW is operational during tests.
- **Test isolation:** Each test should be independent. MSW's `afterEach(() => server.resetHandlers())` ensures no test pollution across test files.