import { useEffect, useState } from 'react';
import { api, type Identity } from './api';

/**
 * The signed-in manager, from the identity headers Databricks Apps injects.
 * Returns `null` until it resolves, and stays `null` if the lookup fails.
 */
export function useIdentity(): Identity | null {
  const [identity, setIdentity] = useState<Identity | null>(null);

  useEffect(() => {
    let active = true;
    api
      .whoami()
      .then((value) => {
        if (active) setIdentity(value);
      })
      .catch(() => {
        // Non-fatal: the UI falls back to "Signed in" without an address.
      });
    return () => {
      active = false;
    };
  }, []);

  return identity;
}
