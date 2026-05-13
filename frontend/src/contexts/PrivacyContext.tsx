import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

interface PrivacyContextType {
  privacyMode: boolean;
  togglePrivacy: () => void;
  mask: (value: string | number | undefined | null) => string;
}

const PrivacyContext = createContext<PrivacyContextType>({
  privacyMode: false,
  togglePrivacy: () => {},
  mask: (v) => String(v ?? ''),
});

export function PrivacyProvider({ children }: { children: ReactNode }) {
  const [privacyMode, setPrivacyMode] = useState(false);
  const togglePrivacy = useCallback(() => setPrivacyMode((p) => !p), []);
  const mask = useCallback(
    (value: string | number | undefined | null) => {
      if (privacyMode) return '•••••';
      return String(value ?? '');
    },
    [privacyMode]
  );

  return (
    <PrivacyContext.Provider value={{ privacyMode, togglePrivacy, mask }}>
      {children}
    </PrivacyContext.Provider>
  );
}

export const usePrivacy = () => useContext(PrivacyContext);
