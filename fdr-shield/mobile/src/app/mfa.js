import { useState } from 'react';
import { router } from 'expo-router';
import { Button, Card, Field, Screen } from '../components/ui';
import { useAuth } from '../providers/AuthProvider';
import { Text } from 'react-native';

export default function MfaScreen() {
  const { verifyMfa, mfa }=useAuth();
  const [code,setCode]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function submit(){setBusy(true);setError('');try{await verifyMfa(code);router.replace('/(portal)')}catch(e){setError(e.message||'Code could not be verified.')}finally{setBusy(false)}}
  if(!mfa){router.replace('/login');return null;}
  return <Screen title="Two-factor verification" subtitle="Enter the current six-digit code from your authenticator app."><Card>
    <Field label="Authenticator code" value={code} onChangeText={value=>setCode(value.replace(/\D/g,'').slice(0,6))} keyboardType="number-pad" placeholder="000000"/>
    {error?<Text accessibilityRole="alert" style={{color:'#B42318'}}>{error}</Text>:null}
    <Button title={busy?'Verifying…':'Verify identity'} onPress={submit} disabled={busy||code.length!==6}/>
  </Card></Screen>;
}
