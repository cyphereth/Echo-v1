import { useState, useEffect } from 'react';
import { getBrands } from '../services/api';

export function useBrands() {
  const [brands,  setBrands]  = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    getBrands()
      .then(data => { setBrands(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(e  => { setError(e.message); setLoading(false); });
  }, []);

  return { brands, loading, error };
}
